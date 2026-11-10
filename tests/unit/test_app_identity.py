"""A new app gets its own name and application id instead of the scaffold's."""

import os
import re
import shutil

from painkiller.core.app_identity import app_id_for, personalize_scaffold
from painkiller.core.templates import builtin_template

SCAFFOLD = builtin_template("capacitor-react").scaffold_dir
FILES = [
    "capacitor.config.ts",
    "android/app/build.gradle",
    "android/app/src/main/res/values/strings.xml",
    "index.html",
    "src/pages/Home.tsx",
]


def _copy(tmp_path) -> str:
    for relative in FILES:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(SCAFFOLD, relative), target)
    return str(tmp_path)


def _read(repo: str, relative: str) -> str:
    with open(os.path.join(repo, relative), encoding="utf-8") as f:
        return f.read()


def test_app_id_is_a_valid_unique_android_id():
    assert app_id_for("lista-de-compras", "a1b2c3") == "app.painkiller.listadecompras_a1b2c3"
    # Nunca começa por dígito nem vira palavra reservada do Java.
    for slug in ("2048", "new", "", "ção"):
        assert re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", app_id_for(slug, "0f0f0f"))
    assert app_id_for("new", "0f0f0f").split(".")[-1] == "new_0f0f0f"


def test_scaffold_gets_the_project_name_and_id(tmp_path):
    repo = _copy(tmp_path)

    changed = personalize_scaffold(repo, "Lista de Compras", "app.painkiller.lista_a1b2c3")

    assert sorted(changed) == sorted(FILES)
    config = _read(repo, "capacitor.config.ts")
    assert "appId: 'app.painkiller.lista_a1b2c3'" in config and 'appName: "Lista de Compras"' in config
    gradle = _read(repo, "android/app/build.gradle")
    assert 'applicationId "app.painkiller.lista_a1b2c3"' in gradle
    # O pacote do código Java não muda: MainActivity continua em com.example.myapp.
    assert 'namespace = "com.example.myapp"' in gradle
    strings = _read(repo, "android/app/src/main/res/values/strings.xml")
    assert '<string name="app_name">Lista de Compras</string>' in strings
    assert '<string name="package_name">app.painkiller.lista_a1b2c3</string>' in strings
    assert "<title>Lista de Compras</title>" in _read(repo, "index.html")
    assert '<IonTitle>{"Lista de Compras"}</IonTitle>' in _read(repo, "src/pages/Home.tsx")
    for relative in FILES:
        assert "My App" not in _read(repo, relative)


def test_awkward_names_are_escaped_per_file(tmp_path):
    repo = _copy(tmp_path)

    personalize_scaffold(repo, "Tom & Jerry's <App>\n\"2\"", "app.painkiller.tom_a1b2c3")

    assert 'appName: "Tom & Jerry\'s <App> \\"2\\""' in _read(repo, "capacitor.config.ts")
    strings = _read(repo, "android/app/src/main/res/values/strings.xml")
    assert '<string name="app_name">Tom &amp; Jerry\\\'s &lt;App&gt; \\"2\\"</string>' in strings
    assert "<title>Tom &amp; Jerry's &lt;App&gt; \"2\"</title>" in _read(repo, "index.html")


def test_a_scaffold_with_its_own_identity_is_left_alone(tmp_path):
    repo = _copy(tmp_path)
    personalize_scaffold(repo, "Primeiro", "app.painkiller.primeiro_111111")

    assert personalize_scaffold(repo, "Segundo", "app.painkiller.segundo_222222") == []
    assert "primeiro_111111" in _read(repo, "capacitor.config.ts")
