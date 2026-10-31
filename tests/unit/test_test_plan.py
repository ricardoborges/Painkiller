"""Discovery of where a target repo's pytest suite has to run from."""

import json
import shutil
import subprocess

import pytest

from painkiller.core.test_plan import build_test_script, find_test_roots


def _touch(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_root_config_wins(tmp_path):
    _touch(tmp_path / "pyproject.toml", "[tool.pytest.ini_options]\n")
    _touch(tmp_path / "backend" / "tests" / "test_a.py")
    assert find_test_roots(str(tmp_path)) == ["."]


def test_subfolder_with_tests_dir_is_its_own_root(tmp_path):
    _touch(tmp_path / "backend" / "tests" / "test_a.py")
    _touch(tmp_path / "frontend" / "node_modules" / "x" / "tests" / "test_b.py")
    _touch(tmp_path / "worker" / "pytest.ini", "[pytest]\n")
    assert find_test_roots(str(tmp_path)) == ["backend", "worker"]


def test_loose_test_files_run_from_the_root(tmp_path):
    _touch(tmp_path / "test_x.py")
    assert find_test_roots(str(tmp_path)) == ["."]


def test_no_python_tests(tmp_path):
    _touch(tmp_path / "index.html")
    assert find_test_roots(str(tmp_path)) == []
    assert build_test_script(str(tmp_path)) is None


def test_existing_venv_is_used_instead_of_installing(tmp_path):
    _touch(tmp_path / "tests" / "test_a.py")
    _touch(tmp_path / "requirements.txt", "x\n")
    _touch(tmp_path / ".venv" / "bin" / "python")
    script = build_test_script(str(tmp_path))
    assert ".venv/bin/python -m pytest" in script
    assert "pip install" not in script


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")
@pytest.mark.parametrize(
    "codes, expected",
    [((0, 5), 0), ((5, 5), 5), ((5, 1), 1), ((2, 0), 2)],
)
def test_script_aggregates_exit_codes(tmp_path, codes, expected):
    # Troca o pytest por um `python3` falso que sai com os códigos dados, em ordem.
    _touch(tmp_path / "a" / "tests" / "test_a.py")
    _touch(tmp_path / "b" / "tests" / "test_b.py")
    script = build_test_script(str(tmp_path)).replace("/workspace", tmp_path.as_posix())
    fake = tmp_path / "bin" / "python3"
    _touch(fake, "#!/bin/sh\nn=$(cat \"$CODES\" | head -1)\nsed -i 1d \"$CODES\"\nexit $n\n")
    fake.chmod(0o755)
    (tmp_path / "codes").write_text("\n".join(str(c) for c in codes) + "\n")
    env = {"PATH": f"{(tmp_path / 'bin').as_posix()}:/usr/bin:/bin", "CODES": (tmp_path / "codes").as_posix()}
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True)
    assert proc.returncode == expected


def test_gradle_project_runs_unit_tests_and_debug_build(tmp_path):
    _touch(tmp_path / "settings.gradle.kts", 'include(":app")\n')
    _touch(tmp_path / "gradlew", "#!/bin/sh\n")
    # Um script Python solto não tira o app Android do Gradle.
    _touch(tmp_path / "tools" / "tests" / "test_x.py")

    script = build_test_script(str(tmp_path))

    assert "sh ./gradlew" in script
    assert "testDebugUnitTest assembleDebug" in script
    assert "pytest" not in script


def test_gradle_without_wrapper_uses_installed_gradle(tmp_path):
    _touch(tmp_path / "settings.gradle", "")
    assert "exec gradle " in build_test_script(str(tmp_path))


def _package_json(dependencies):
    """Formatted like npm writes it: one dependency per line."""
    return json.dumps({"dependencies": dependencies}, indent=2) + "\n"


def _capacitor_repo(tmp_path):
    """A committed Capacitor app on main, checked out on a task branch."""
    repo = tmp_path / "repo"
    _touch(repo / "package.json", _package_json({"@capacitor/core": "^8.6.0"}))
    _touch(repo / "capacitor.config.ts", "export default {}\n")
    _touch(repo / "src" / "App.tsx", "export {}\n")
    _touch(repo / "android" / "gradlew", "#!/bin/sh\necho gradlew \"$@\" >> \"$CALLS\"\n")
    _touch(repo / ".gitignore", "node_modules/\n")
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git + ["init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(git + ["add", "-A"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-qm", "scaffold"], cwd=repo, check=True)
    subprocess.run(git + ["checkout", "-qb", "feature/t1"], cwd=repo, check=True)
    return repo


def _run_capacitor(tmp_path, repo, failing=""):
    """Run the script against fake npm/npx; returns (exit code, recorded calls)."""
    bin_dir = tmp_path / "bin"
    for tool in ("npm", "npx", "python3"):
        _touch(
            bin_dir / tool,
            f'#!/bin/sh\necho {tool} "$@" >> "$CALLS"\n'
            f'[ "{tool} $1" = "{failing}" ] && exit 3\nexit 0\n',
        )
        (bin_dir / tool).chmod(0o755)
    calls = tmp_path / "calls"
    calls.write_text("")
    script = build_test_script(str(repo), base_branch="main").replace("/workspace", repo.as_posix())
    env = {
        "PATH": f"{bin_dir.as_posix()}:/usr/bin:/bin",
        "CALLS": calls.as_posix(),
        "HOME": tmp_path.as_posix(),
    }
    proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True)
    return proc.returncode, calls.read_text().splitlines()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_web_only_change_skips_the_apk(tmp_path):
    repo = _capacitor_repo(tmp_path)
    _touch(repo / "src" / "App.tsx", "export const x = 1\n")
    _touch(repo / "src" / "pages" / "List.tsx", "export {}\n")

    code, calls = _run_capacitor(tmp_path, repo)

    assert code == 0
    assert [c.split()[:2] for c in calls] == [
        ["npm", "install"], ["npm", "test"], ["npm", "run"], ["npx", "--no-install"],
    ]


PREVIEW_BUILD = "npx --no-install vite build --base ./ --outDir .painkiller/preview-build --emptyOutDir --logLevel warn"


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_builds_the_preview_with_relative_paths(tmp_path):
    repo = _capacitor_repo(tmp_path)
    # Sobra de uma execução anterior: não pode virar a prévia desta tarefa.
    _touch(repo / ".painkiller" / "preview-build" / "index.html", "old")

    code, calls = _run_capacitor(tmp_path, repo)

    assert code == 0
    assert calls.index(PREVIEW_BUILD) == calls.index("npm run build") + 1
    assert not (repo / ".painkiller" / "preview-build").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_preview_failure_does_not_fail_the_task(tmp_path):
    repo = _capacitor_repo(tmp_path)

    code, calls = _run_capacitor(tmp_path, repo, failing="npx --no-install")

    assert code == 0
    assert PREVIEW_BUILD in calls


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
@pytest.mark.parametrize("change", ["android", "config", "plugin"])
def test_capacitor_native_change_builds_the_apk(tmp_path, change):
    repo = _capacitor_repo(tmp_path)
    if change == "android":
        _touch(repo / "android" / "app" / "src" / "main" / "AndroidManifest.xml", "<manifest/>\n")
    elif change == "config":
        _touch(repo / "capacitor.config.ts", "export default { appId: 'x' }\n")
    else:
        _touch(repo / "package.json", _package_json({"@capacitor/camera": "^8.0.0", "@capacitor/core": "^8.6.0"}))

    code, calls = _run_capacitor(tmp_path, repo)

    assert code == 0
    assert "npx cap sync android" in calls
    assert calls[-1] == "gradlew --no-daemon --console=plain --stacktrace assembleDebug"


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_non_capacitor_dependency_skips_the_apk(tmp_path):
    repo = _capacitor_repo(tmp_path)
    _touch(repo / "package.json", _package_json({"@capacitor/core": "^8.6.0", "react": "^19.3.1", "zod": "^4.0.0"}))

    code, calls = _run_capacitor(tmp_path, repo)

    assert code == 0
    assert not any(c.startswith(("npx cap", "gradlew")) for c in calls)


def _with_backend(repo):
    """Commit a backend/ on main, then come back to the task branch."""
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(git + ["checkout", "-q", "main"], cwd=repo, check=True)
    _touch(repo / "backend" / "Dockerfile", "FROM python:3.13-slim\n")
    _touch(repo / "backend" / "requirements.txt", "fastapi\n")
    _touch(repo / "backend" / "app" / "main.py", "app = None\n")
    subprocess.run(git + ["add", "-A"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-qm", "backend"], cwd=repo, check=True)
    subprocess.run(git + ["checkout", "-q", "feature/t1"], cwd=repo, check=True)
    subprocess.run(git + ["merge", "-q", "main"], cwd=repo, check=True)


PYTEST = "python3 -m pytest -p no:cacheprovider --rootdir=."


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_backend_change_runs_its_pytest_before_skipping_the_apk(tmp_path):
    repo = _capacitor_repo(tmp_path)
    _with_backend(repo)
    _touch(repo / "backend" / "app" / "main.py", "app = 1\n")

    code, calls = _run_capacitor(tmp_path, repo)

    assert code == 0
    assert calls.index(PYTEST) > calls.index("npm run build")
    # Os requirements do backend são reinstalados antes: o contêiner do agente morreu.
    assert calls[calls.index(PYTEST) - 1].startswith("python3 -m pip install")
    assert not any(c.startswith("gradlew") for c in calls)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_app_only_change_skips_the_backend(tmp_path):
    repo = _capacitor_repo(tmp_path)
    _with_backend(repo)
    _touch(repo / "src" / "App.tsx", "export const y = 2\n")

    code, calls = _run_capacitor(tmp_path, repo)

    assert code == 0
    assert not any(c.startswith("python3") for c in calls)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_failing_backend_tests_fail_the_task(tmp_path):
    repo = _capacitor_repo(tmp_path)
    _with_backend(repo)
    _touch(repo / "backend" / "tests" / "test_x.py", "def test_x(): pass\n")

    code, calls = _run_capacitor(tmp_path, repo, failing="python3 -m")

    assert code == 3
    assert calls[-1] == PYTEST


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_backend_change_still_builds_the_apk_when_native_changed(tmp_path):
    repo = _capacitor_repo(tmp_path)
    _with_backend(repo)
    _touch(repo / "backend" / "app" / "main.py", "app = 1\n")
    _touch(repo / "capacitor.config.ts", "export default { appId: 'x' }\n")

    code, calls = _run_capacitor(tmp_path, repo)

    assert code == 0
    assert calls.index(PYTEST) < calls.index("npx cap sync android")
    assert calls[-1].startswith("gradlew")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_capacitor_failing_tests_stop_before_the_build(tmp_path):
    repo = _capacitor_repo(tmp_path)

    code, calls = _run_capacitor(tmp_path, repo, failing="npm test")

    assert code == 3
    assert calls == ["npm install --no-audit --no-fund --loglevel=error", "npm test"]


def test_capacitor_wins_over_its_own_gradle_build(tmp_path):
    # O app Capacitor tem Gradle em android/, nunca na raiz; mesmo que tivesse, o Capacitor vence.
    _touch(tmp_path / "package.json", "{}\n")
    _touch(tmp_path / "capacitor.config.json", "{}\n")
    _touch(tmp_path / "settings.gradle", "")

    script = build_test_script(str(tmp_path))

    assert "npm test" in script and "testDebugUnitTest" not in script
