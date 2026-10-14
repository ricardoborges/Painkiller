"""Discovery of where a target repo's pytest suite has to run from."""

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
