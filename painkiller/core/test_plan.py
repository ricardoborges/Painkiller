"""How a target repo's tests run: Capacitor, Gradle for the Android app, pytest as a fallback.

Esta edição fabrica apps Android: um repositório com build Gradle na raiz roda
os testes unitários JVM e monta o APK de debug (não há emulador no worker, então
androidTest fica de fora). Um app Capacitor roda os testes e o build web e só
monta o APK quando a tarefa mexeu na parte nativa. Sem nenhum dos dois, vale a
busca por suítes pytest abaixo.

The suite runs inside the worker image (the repo mounted at ``/workspace``),
never in the API process: it is code the agent wrote. A repo whose tests sit
in a subfolder (``backend/tests`` importing ``app``) has to be run from that
folder, or pytest walks up looking for a config and nothing imports.
"""

import os
import shlex
from typing import Optional

from painkiller.core.preview import PREVIEW_STAGING_RELATIVE

#: Pastas que nunca contêm a suíte do projeto (dependências, artefatos, estado do Painkiller).
SKIP_DIRS = {
    ".git", ".painkiller", ".harness", "node_modules", ".venv", "venv", "env",
    "__pycache__", "dist", "build", ".tox", ".pytest_cache", "site-packages",
}

#: Profundidade máxima procurada a partir da raiz do repositório.
MAX_DEPTH = 3

WORKSPACE = "/workspace"

#: Código de saída do pytest quando nada foi coletado.
NO_TESTS_COLLECTED = 5


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _has_pytest_config(folder: str) -> bool:
    if os.path.isfile(os.path.join(folder, "pytest.ini")):
        return True
    if "[tool.pytest" in _read(os.path.join(folder, "pyproject.toml")):
        return True
    if "[tool:pytest]" in _read(os.path.join(folder, "setup.cfg")):
        return True
    return "[pytest]" in _read(os.path.join(folder, "tox.ini"))


def _has_test_files(folder: str) -> bool:
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if any(f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")) for f in files):
            return True
    return False


def find_test_roots(repo_path: str) -> list[str]:
    """Folders (relative, ``"."`` for the root) pytest should be run from.

    A folder with a pytest config wins over anything below it; otherwise the
    parent of a ``tests``/``test`` folder holding test files is a root, so
    ``backend/tests`` runs from ``backend/`` and ``import app`` resolves.
    """
    roots: list[str] = []

    def visit(folder: str, depth: int) -> None:
        rel = os.path.relpath(folder, repo_path).replace(os.sep, "/")
        if _has_pytest_config(folder):
            roots.append(rel)
            return
        try:
            entries = sorted(os.listdir(folder))
        except OSError:
            return
        if any(
            name in ("tests", "test") and _has_test_files(os.path.join(folder, name))
            for name in entries
        ):
            roots.append(rel)
            return
        if depth >= MAX_DEPTH:
            return
        for name in entries:
            child = os.path.join(folder, name)
            if name in SKIP_DIRS or name.startswith(".") or not os.path.isdir(child):
                continue
            visit(child, depth + 1)

    visit(repo_path, 0)
    if not roots and _has_test_files(repo_path):
        # Testes soltos (test_*.py fora de uma pasta tests/): roda da raiz.
        roots.append(".")
    return roots


def _install_deps(folder: str) -> list[str]:
    """Commands that install a root's dependencies before its tests run.

    O worker é one-shot: o que o agente instalou no Python do sistema morreu
    com o contêiner dele. O cache de pacotes do projeto deixa isto rápido.
    """
    pip = "python3 -m pip install -q --disable-pip-version-check --break-system-packages"
    commands: list[str] = []
    names = set(os.listdir(folder)) if os.path.isdir(folder) else set()
    for req in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt", "requirements-test.txt"):
        if req in names:
            commands.append(f"{pip} -r {req}")
    if not commands and ("pyproject.toml" in names or "setup.py" in names):
        pyproject = _read(os.path.join(folder, "pyproject.toml"))
        if "setup.py" in names or "[project]" in pyproject or "[tool.poetry]" in pyproject:
            commands.append(f"( {pip} -e '.[dev]' || {pip} -e . )")
    return commands


#: Arquivos que marcam um build Gradle na raiz do repositório.
GRADLE_MARKERS = ("settings.gradle.kts", "settings.gradle", "gradlew")

#: Testes unitários JVM e o APK de debug: um app que não monta não passa.
GRADLE_TASKS = "testDebugUnitTest assembleDebug"


def is_gradle_project(repo_path: str) -> bool:
    return any(os.path.isfile(os.path.join(repo_path, name)) for name in GRADLE_MARKERS)


def build_gradle_script(repo_path: str) -> str:
    """POSIX sh script running the Android app's unit tests and debug build."""
    # sh ./gradlew: o bit de execução se perde num bind mount vindo do Windows.
    gradle = "sh ./gradlew" if os.path.isfile(os.path.join(repo_path, "gradlew")) else "gradle"
    lines = [
        f"echo '=== gradle {GRADLE_TASKS}'",
        f"cd {WORKSPACE}",
        f"exec {gradle} --no-daemon --console=plain --stacktrace {GRADLE_TASKS}",
    ]
    return "\n".join(lines) + "\n"


#: Configuração do Capacitor na raiz: marca um app web empacotado como Android.
CAPACITOR_MARKERS = ("capacitor.config.ts", "capacitor.config.json", "capacitor.config.js")

#: Caminhos cuja mudança obriga a montar o APK: o projeto nativo e a configuração do Capacitor.
CAPACITOR_NATIVE_PATHS = r"^(android/|capacitor\.config\.)"


def is_capacitor_project(repo_path: str) -> bool:
    return os.path.isfile(os.path.join(repo_path, "package.json")) and any(
        os.path.isfile(os.path.join(repo_path, name)) for name in CAPACITOR_MARKERS
    )


def build_capacitor_script(base_branch: str = "main") -> str:
    """POSIX sh script for a Capacitor app: web tests and build, the APK only when native code changed.

    O Gradle custa minutos e gigabytes de RAM; a maioria das tarefas só mexe em
    src/. Ele roda quando a tarefa tocou android/, capacitor.config.* ou um
    plugin @capacitor/* do package.json, e também quando não há base para comparar.
    """
    base = shlex.quote(base_branch)
    lines = [
        f"cd {WORKSPACE}",
        # Um bind mount vindo do Windows tem outro dono: o git recusaria o repositório.
        f'g() {{ git -c safe.directory={WORKSPACE} "$@"; }}',
        "echo '=== npm install'",
        "npm install --no-audit --no-fund --loglevel=error || exit $?",
        "echo '=== npm test'",
        "npm test || exit $?",
        "echo '=== npm run build'",
        "npm run build || exit $?",
        # Prévia para a UI: o mesmo app com caminhos relativos, servido sob um
        # prefixo. Nunca reprova a tarefa; sem ela a UI só não se atualiza.
        "echo '=== prévia web'",
        f"rm -rf {PREVIEW_STAGING_RELATIVE}",
        f"npx --no-install vite build --base ./ --outDir {PREVIEW_STAGING_RELATIVE} --emptyOutDir "
        f"--logLevel warn || {{ rm -rf {PREVIEW_STAGING_RELATIVE}; echo 'aviso: prévia não montada'; }}",
        f"base=$(g merge-base HEAD {base} 2>/dev/null)",
        "native=0",
        '[ -n "$base" ] || native=1',
        f'{{ g diff --name-only "$base"; g ls-files --others --exclude-standard; }} 2>/dev/null '
        f"| grep -Eq '{CAPACITOR_NATIVE_PATHS}' && native=1",
        # Plugins comparados como conjunto: a vírgula que o npm acrescenta numa linha
        # vizinha não é mudança nativa.
        """caps() { grep -o '"@capacitor/[^"]*"[[:space:]]*:[[:space:]]*"[^"]*"' | sort; }""",
        """[ "$(g show "$base:package.json" 2>/dev/null | caps)" = "$(caps < package.json)" ] || native=1""",
        'if [ "$native" -eq 0 ]; then',
        "  echo '=== android/ intocado: o APK não é montado nesta tarefa'",
        "  exit 0",
        "fi",
        "echo '=== npx cap sync android'",
        "npx cap sync android || exit $?",
        "echo '=== gradle assembleDebug'",
        "cd android || exit 1",
        # sh ./gradlew: o bit de execução se perde num bind mount vindo do Windows.
        "exec sh ./gradlew --no-daemon --console=plain --stacktrace assembleDebug",
    ]
    return "\n".join(lines) + "\n"


def build_test_script(repo_path: str, base_branch: str = "main") -> Optional[str]:
    """POSIX sh script that runs the repo's tests, or None when it has none.

    A Capacitor app or a Gradle build at the root wins outright, in that order
    (the Capacitor app keeps its Gradle build under android/). Otherwise every pytest root runs;
    the script exits with the first real failure; a root that collects nothing (pytest's 5)
    does not fail the run, and the script exits 5 only when every root was empty.
    """
    if is_capacitor_project(repo_path):
        return build_capacitor_script(base_branch)
    if is_gradle_project(repo_path):
        return build_gradle_script(repo_path)
    roots = find_test_roots(repo_path)
    if not roots:
        return None

    lines = ["rc=0", "ran=0"]
    for rel in roots:
        folder = repo_path if rel == "." else os.path.join(repo_path, *rel.split("/"))
        workdir = WORKSPACE if rel == "." else f"{WORKSPACE}/{rel}"
        label = shlex.quote(rel)
        lines.append(f"echo '=== pytest em '{label}")
        lines.append(f"cd {shlex.quote(workdir)}")
        if os.path.isfile(os.path.join(folder, ".venv", "bin", "python")):
            python = ".venv/bin/python"
        else:
            python = "python3"
            for command in _install_deps(folder):
                lines.append(f"{command} || echo 'aviso: falha ao instalar dependências em '{label}")
        # --rootdir fixa a raiz no próprio root; sem isso o pytest sobe procurando config.
        lines.append(f"{python} -m pytest -p no:cacheprovider --rootdir=. ; code=$?")
        lines.append(
            f'if [ "$code" -eq {NO_TESTS_COLLECTED} ]; then :; '
            'elif [ "$code" -ne 0 ]; then [ "$rc" -eq 0 ] && rc=$code; ran=1; else ran=1; fi'
        )
    lines.append(f'if [ "$rc" -ne 0 ]; then exit "$rc"; fi')
    lines.append(f'if [ "$ran" -eq 0 ]; then exit {NO_TESTS_COLLECTED}; fi')
    lines.append("exit 0")
    return "\n".join(lines) + "\n"
