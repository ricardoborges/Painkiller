"""Name and Android application id of a newly scaffolded app.

O arcabouço embutido nasce como "My App" / ``com.example.myapp``. Sem trocar,
todo app da plataforma teria o mesmo identificador: dois deles não convivem no
mesmo celular e a Play Store recusa ``com.example``. Só os valores de fábrica
são substituídos; um arcabouço do admin com identidade própria fica como está.
"""

import html
import json
import os
import re

PLACEHOLDER_ID = "com.example.myapp"
PLACEHOLDER_NAME = "My App"

#: Prefixo do identificador gerado; o resto é o nome do projeto e o código dele.
APP_ID_PREFIX = "app.painkiller"


def app_id_for(name_slug: str, code: str) -> str:
    """Unique, valid application id: ``app.painkiller.<name>_<code>``.

    Um segmento só para nome e código: assim ele nunca é uma palavra reservada
    do Java (um projeto chamado "new") e sempre começa por letra.
    """
    name = re.sub(r"[^a-z0-9]", "", name_slug.lower()) or "app"
    if not name[0].isalpha():
        name = f"a{name}"
    suffix = re.sub(r"[^a-z0-9]", "", code.lower())
    return f"{APP_ID_PREFIX}.{name}_{suffix}" if suffix else f"{APP_ID_PREFIX}.{name}"


def clean_app_name(name: str) -> str:
    """The project's name as a launcher label: one line, no control characters."""
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", name)).strip() or PLACEHOLDER_NAME


def _android_string(text: str) -> str:
    """Escape a value for an Android ``<string>`` resource."""
    escaped = text.replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    escaped = escaped.replace("'", "\\'").replace('"', '\\"')
    return f"\\{escaped}" if escaped[:1] in ("@", "?") else escaped


def _rewrite(path: str, edit) -> bool:
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            source = f.read()
    except OSError:
        return False
    updated = edit(source)
    if updated == source:
        return False
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(updated)
    return True


def personalize_scaffold(repo_path: str, app_name: str, app_id: str) -> list[str]:
    """Replace the factory name and id of a Capacitor scaffold; returns the files changed.

    O ``namespace`` do Gradle (pacote do código Java) fica: só o ``applicationId``
    identifica o app instalado, e mover o pacote exigiria mover os fontes.
    """
    name = clean_app_name(app_name)
    quoted = json.dumps(name, ensure_ascii=False)
    old_id = re.escape(PLACEHOLDER_ID)
    old_name = re.escape(PLACEHOLDER_NAME)

    def config(source: str) -> str:
        source = re.sub(rf"(appId\"?\s*:\s*)(['\"]){old_id}\2", lambda m: f"{m.group(1)}{m.group(2)}{app_id}{m.group(2)}", source)
        return re.sub(rf"(appName\"?\s*:\s*)(['\"]){old_name}\2", lambda m: f"{m.group(1)}{quoted}", source)

    def gradle(source: str) -> str:
        return re.sub(rf"(applicationId\s+)(['\"]){old_id}\2", lambda m: f'{m.group(1)}"{app_id}"', source)

    def strings(source: str) -> str:
        label = _android_string(name)
        for key in ("app_name", "title_activity_main"):
            source = re.sub(
                rf'(<string name="{key}">){old_name}(</string>)', lambda m: f"{m.group(1)}{label}{m.group(2)}", source
            )
        for key in ("package_name", "custom_url_scheme"):
            source = re.sub(
                rf'(<string name="{key}">){old_id}(</string>)', lambda m: f"{m.group(1)}{app_id}{m.group(2)}", source
            )
        return source

    def page_title(source: str) -> str:
        return source.replace(f"<title>{PLACEHOLDER_NAME}</title>", f"<title>{html.escape(name, quote=False)}</title>")

    def home(source: str) -> str:
        # Expressão JSX: o nome pode ter chaves, aspas ou "<".
        return source.replace(f"<IonTitle>{PLACEHOLDER_NAME}</IonTitle>", f"<IonTitle>{{{quoted}}}</IonTitle>")

    edits = [
        ("capacitor.config.ts", config),
        ("capacitor.config.json", config),
        ("android/app/build.gradle", gradle),
        ("android/app/src/main/res/values/strings.xml", strings),
        ("index.html", page_title),
        ("src/pages/Home.tsx", home),
    ]
    changed = []
    for relative, edit in edits:
        if _rewrite(os.path.join(repo_path, *relative.split("/")), edit):
            changed.append(relative)
    return changed
