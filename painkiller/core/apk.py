"""Building the project's APK on demand: debug to install and test, release signed to publish.

O build roda num worker (o código é do agente, nunca no processo da API) a
partir de um clone da branch padrão dentro do contêiner: a árvore de trabalho
do repositório pode estar numa feature/ no meio de uma tarefa, e o APK tem de
ser exatamente o que foi incorporado.

O release é montado sem assinatura e assinado num segundo contêiner, o único
que monta o volume da chave do projeto (``signing_volume``). O primeiro roda o
Gradle e os scripts npm do repositório — código do agente — e por isso nunca
vê a chave. A chave nasce no primeiro release e é a mesma para sempre: perder
o volume impede publicar atualizações do app na loja — por isso excluir o
projeto não o apaga (o repositório no Gitea também só é arquivado).
"""

import os
import re
import shlex
import shutil
from typing import Iterable, Optional

from painkiller.core.test_plan import WORKSPACE, is_capacitor_project, is_gradle_project

#: Um diretório por build, fora do git (``.painkiller/`` não é versionado).
APKS_RELATIVE = ".painkiller/apks"

#: Nome do arquivo final dentro do diretório do build.
APK_FILE = "app.apk"
UNSIGNED_FILE = "unsigned.apk"

#: Linha que o script imprime com o commit montado.
COMMIT_MARKER = "PAINKILLER_COMMIT="

#: Builds mantidos no disco por projeto; o último release válido nunca é podado.
KEEP_BUILDS = 10

SIGNING_MOUNT = "/signing"
OUT_MOUNT = "/out"


def signing_volume(project_id: str) -> str:
    """Named volume with the project's release keystore, mounted only into the signing step."""
    return f"painkiller-signing-{project_id}"


def build_dir(repo_path: str, build_id: str) -> str:
    return os.path.join(repo_path, *APKS_RELATIVE.split("/"), build_id)


def apk_path(repo_path: str, build_id: str) -> str:
    return os.path.join(build_dir(repo_path, build_id), APK_FILE)


def is_android_project(repo_path: str) -> bool:
    return is_capacitor_project(repo_path) or is_gradle_project(repo_path)


def build_apk_script(repo_path: str, build_id: str, variant: str, branch: str) -> Optional[str]:
    """POSIX sh script that builds the APK of ``branch``; None when the repo has no Android build.

    Debug sai assinado com a chave de debug do SDK (instalável direto); release
    sai sem assinatura, como ``unsigned.apk``, para o passo de assinatura.
    """
    capacitor = is_capacitor_project(repo_path)
    if not capacitor and not is_gradle_project(repo_path):
        return None
    task = "assembleRelease" if variant == "release" else "assembleDebug"
    out = f"{WORKSPACE}/{APKS_RELATIVE}/{build_id}"
    target = UNSIGNED_FILE if variant == "release" else APK_FILE
    lines = [
        f"echo '=== clone de '{shlex.quote(branch)}",
        "rm -rf /tmp/src",
        # Um bind mount vindo do Windows tem outro dono: o git recusaria o repositório.
        f"git -c safe.directory='*' clone --quiet --no-hardlinks --branch {shlex.quote(branch)} "
        f"{WORKSPACE} /tmp/src || exit $?",
        "cd /tmp/src",
        f'echo "{COMMIT_MARKER}$(git rev-parse --short HEAD)"',
    ]
    if capacitor:
        lines += [
            "echo '=== npm install'",
            "npm install --no-audit --no-fund --loglevel=error || exit $?",
            "echo '=== npm run build'",
            "npm run build || exit $?",
            "echo '=== npx cap sync android'",
            "npx cap sync android || exit $?",
            "cd android || exit 1",
        ]
    lines += [
        f"echo '=== gradle {task}'",
        # sh ./gradlew: o bit de execução se perde num bind mount vindo do Windows.
        f"sh ./gradlew --no-daemon --console=plain --stacktrace {task} || exit $?",
        f"apk=$(find . -path '*/build/outputs/apk/{variant}/*.apk' | head -n 1)",
        "[ -n \"$apk\" ] || { echo 'nenhum APK foi gerado'; exit 1; }",
        f"mkdir -p {out}",
        f'cp "$apk" {out}/{target} || exit $?',
        f"echo '=== APK: '\"$apk\"",
    ]
    return "\n".join(lines) + "\n"


def _distinguished_name(app_name: str) -> str:
    # Vírgula, sinal de igual e aspas quebrariam o -dname do keytool.
    cleaned = re.sub(r"[^0-9A-Za-zÀ-ÿ \-_.]", "", app_name).strip() or "Painkiller app"
    return f"CN={cleaned[:64]}"


def sign_apk_script() -> str:
    """POSIX sh script that signs ``/out/unsigned.apk`` with the project's key, creating it on first use."""
    lines = [
        'bt=$(ls -d "$ANDROID_HOME"/build-tools/* 2>/dev/null | sort -V | tail -n 1)',
        "[ -n \"$bt\" ] || { echo 'build-tools do Android SDK não encontrado'; exit 1; }",
        f"if [ ! -f {SIGNING_MOUNT}/release.jks ]; then",
        "  echo '=== gerando a chave de assinatura do projeto'",
        "  pw=$(head -c 64 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)",
        f'  keytool -genkeypair -noprompt -keystore {SIGNING_MOUNT}/release.jks -storetype PKCS12 '
        '-alias release -keyalg RSA -keysize 4096 -validity 10000 '
        '-storepass "$pw" -keypass "$pw" -dname "$PK_SIGNING_DN" || exit $?',
        f'  printf %s "$pw" > {SIGNING_MOUNT}/password',
        "fi",
        "echo '=== zipalign'",
        f'"$bt/zipalign" -f -p 4 {OUT_MOUNT}/{UNSIGNED_FILE} {OUT_MOUNT}/aligned.apk || exit $?',
        "echo '=== apksigner'",
        # Sem --key-pass: o apksigner lê cada fonte `file:` como um só fluxo, e a
        # mesma senha nos dois consumia a única linha (EOF na senha da chave).
        # Ausente, ele usa a do keystore, que no PKCS12 é a mesma.
        f'"$bt/apksigner" sign --ks {SIGNING_MOUNT}/release.jks --ks-key-alias release '
        f"--ks-pass file:{SIGNING_MOUNT}/password "
        f"--out {OUT_MOUNT}/{APK_FILE} {OUT_MOUNT}/aligned.apk || exit $?",
        f'"$bt/apksigner" verify {OUT_MOUNT}/{APK_FILE} || exit $?',
        f"rm -f {OUT_MOUNT}/{UNSIGNED_FILE} {OUT_MOUNT}/aligned.apk {OUT_MOUNT}/{APK_FILE}.idsig",
        "echo '=== APK assinado'",
    ]
    return "\n".join(lines) + "\n"


def signing_env(app_name: str) -> dict[str, str]:
    return {"PK_SIGNING_DN": _distinguished_name(app_name)}


def parse_commit(logs: str) -> Optional[str]:
    for line in (logs or "").splitlines():
        if line.startswith(COMMIT_MARKER):
            return line[len(COMMIT_MARKER):].strip() or None
    return None


def prune_builds(repo_path: str, keep_ids: Iterable[str]) -> None:
    """Delete the build folders not in ``keep_ids``; best effort."""
    root = os.path.join(repo_path, *APKS_RELATIVE.split("/"))
    if not os.path.isdir(root):
        return
    keep = set(keep_ids)
    for name in os.listdir(root):
        if name not in keep:
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)
