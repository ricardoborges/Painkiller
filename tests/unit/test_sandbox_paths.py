"""Unit tests for container-to-host path translation in the sandbox runner.

When the API itself runs in a container (see docker-compose.yml) it creates the
agent containers as siblings over the host socket, so the bind-mount source is
resolved by the host daemon and must be rewritten first.
"""

import os
import pytest
from painkiller.adapters.sandbox.docker_runner import DockerSandboxRunner

CONTAINER_ROOT = "/app/storage"
WINDOWS_HOST = r"D:\dev\github\Painkiller\storage"
POSIX_HOST = "/home/ricardo/painkiller/storage"


@pytest.fixture(autouse=True)
def clear_mapping(monkeypatch):
    """Keep the ambient environment from leaking into these cases."""
    monkeypatch.delenv("PAINKILLER_CONTAINER_ROOT", raising=False)
    monkeypatch.delenv("PAINKILLER_HOST_ROOT", raising=False)


def _map(monkeypatch, container_root: str, host_root: str) -> None:
    monkeypatch.setenv("PAINKILLER_CONTAINER_ROOT", container_root)
    monkeypatch.setenv("PAINKILLER_HOST_ROOT", host_root)


def test_rewrites_to_windows_host_path(monkeypatch):
    _map(monkeypatch, CONTAINER_ROOT, WINDOWS_HOST)

    result = DockerSandboxRunner._daemon_path("/app/storage/projects/proj-abc/repo")

    assert result == WINDOWS_HOST + r"\projects\proj-abc\repo"


def test_rewrites_to_posix_host_path(monkeypatch):
    _map(monkeypatch, CONTAINER_ROOT, POSIX_HOST)

    result = DockerSandboxRunner._daemon_path("/app/storage/projects/proj-abc/repo")

    assert result == POSIX_HOST + "/projects/proj-abc/repo"


def test_tolerates_trailing_separators_on_both_roots(monkeypatch):
    _map(monkeypatch, "/app/storage/", "/srv/painkiller/storage/")

    result = DockerSandboxRunner._daemon_path("/app/storage/projects/y/repo")

    assert result == "/srv/painkiller/storage/projects/y/repo"


def test_leaves_paths_outside_the_mapped_root_alone(monkeypatch):
    _map(monkeypatch, CONTAINER_ROOT, WINDOWS_HOST)

    result = DockerSandboxRunner._daemon_path("/tmp/somewhere/else")

    assert result == "/tmp/somewhere/else"


def test_is_inert_without_both_variables(monkeypatch):
    """Running directly on the host is the default and must not be rewritten."""
    path = "/app/storage/projects/x/repo"

    assert DockerSandboxRunner._daemon_path(path) == path

    # A half-configured mapping is ignored rather than half-applied.
    monkeypatch.setenv("PAINKILLER_CONTAINER_ROOT", CONTAINER_ROOT)
    assert DockerSandboxRunner._daemon_path(path) == path


def test_resolves_relative_paths_against_the_cwd(monkeypatch):
    """Without a mapping the runner still needs an absolute source for Docker."""
    result = DockerSandboxRunner._daemon_path("some/relative/repo")

    assert result == os.path.abspath("some/relative/repo")
    assert os.path.isabs(result)
