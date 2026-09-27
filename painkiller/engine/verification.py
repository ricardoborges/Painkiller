"""How a task's result is verified after the coding agent exits 0.

O orquestrador antes rodava `pytest` fixo: qualquer projeto que não fosse
Python (ou que ainda não tivesse testes) falhava sempre, com "no tests
collected" (código 5) ou "command not found" (127). Aqui o comando é
detectado pelo conteúdo do repositório, e a ausência de testes é tratada
como "nada a verificar", não como falha.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

#: pytest sai com 5 quando não coleta nenhum teste.
PYTEST_NO_TESTS = 5


@dataclass
class Verdict:
    passed: bool
    note: str


def detect_test_command(repo_path: str) -> Optional[str]:
    """Pick a verification command from what the repository contains, or None."""
    package_json = os.path.join(repo_path, "package.json")
    if os.path.isfile(package_json):
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                scripts = (json.load(f).get("scripts") or {})
            test_script = str(scripts.get("test") or "")
            if test_script and "no test specified" not in test_script:
                return "npm test"
        except (OSError, ValueError):
            pass

    python_markers = ("pytest.ini", "conftest.py", "tox.ini", "setup.cfg")
    if any(os.path.isfile(os.path.join(repo_path, m)) for m in python_markers):
        return "pytest"
    pyproject = os.path.join(repo_path, "pyproject.toml")
    if os.path.isfile(pyproject):
        try:
            with open(pyproject, "r", encoding="utf-8") as f:
                if "pytest" in f.read():
                    return "pytest"
        except OSError:
            pass
    if _has_python_tests(repo_path):
        return "pytest"

    if os.path.isfile(os.path.join(repo_path, "go.mod")):
        return "go test ./..."
    if os.path.isfile(os.path.join(repo_path, "Cargo.toml")):
        return "cargo test"
    return None


def _has_python_tests(repo_path: str) -> bool:
    for folder in ("tests", "test"):
        path = os.path.join(repo_path, folder)
        if os.path.isdir(path):
            for _, _, files in os.walk(path):
                if any(f.startswith("test_") and f.endswith(".py") for f in files):
                    return True
    return False


def judge(command: str, exit_code: int, output: str) -> Verdict:
    """Translate a test run into pass/fail, tolerating 'nothing to test'."""
    if exit_code == 0:
        return Verdict(True, f"Verificação `{command}` passou.")
    if command.startswith("pytest") and exit_code == PYTEST_NO_TESTS:
        return Verdict(True, "Nenhum teste encontrado; nada a verificar.")
    if exit_code == 127:
        return Verdict(
            False,
            f"O comando de verificação `{command}` não está instalado no ambiente da API.",
        )
    return Verdict(False, output)
