"""Unit tests for verification command detection and result judgement."""

import json
import os

from painkiller.engine.verification import detect_test_command, judge


def test_detects_npm_test(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8")
    assert detect_test_command(str(tmp_path)) == "npm test"


def test_ignores_npm_placeholder_test_script(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}), encoding="utf-8"
    )
    assert detect_test_command(str(tmp_path)) is None


def test_detects_pytest_from_tests_folder(tmp_path):
    os.makedirs(tmp_path / "tests")
    (tmp_path / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
    assert detect_test_command(str(tmp_path)) == "pytest"


def test_detects_pytest_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    assert detect_test_command(str(tmp_path)) == "pytest"


def test_detects_go_and_cargo(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    assert detect_test_command(str(tmp_path)) == "go test ./..."
    os.remove(tmp_path / "go.mod")
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    assert detect_test_command(str(tmp_path)) == "cargo test"


def test_nothing_detected_in_empty_or_missing_repo(tmp_path):
    assert detect_test_command(str(tmp_path)) is None
    assert detect_test_command(str(tmp_path / "missing")) is None


def test_judge():
    assert judge("pytest", 0, "").passed
    assert judge("pytest", 5, "no tests ran").passed
    assert not judge("npm test", 5, "").passed
    assert not judge("npm test", 1, "2 failing").passed
    missing = judge("cargo test", 127, "not found")
    assert not missing.passed
    assert "não está instalado" in missing.note
