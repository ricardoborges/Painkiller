"""Path translation between this process and the Docker daemon."""

import logging
import os
import socket
from pathlib import PurePosixPath
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Caminho de ./storage no host, instalado na subida a partir das configurações
#: da plataforma (salvo no wizard ou detectado).
_host_root: Optional[str] = None


def set_host_root(value: Optional[str]) -> None:
    """Install the host path of the storage folder for this process; None = no rewrite."""
    global _host_root
    _host_root = (value or "").strip() or None


def container_root() -> str:
    return os.environ.get("PAINKILLER_CONTAINER_ROOT", "").strip()


def host_root() -> str:
    return (_host_root or "").rstrip("/\\")


def detect_host_root(client: Any, root: Optional[str] = None) -> Optional[str]:
    """Host path bind-mounted at the container root, read by inspecting our own container.

    O socket do Docker está montado, então a API se enxerga pelo hostname
    (que o Docker define como o id curto do contêiner) e lê em `Mounts` a
    origem do destino. É o caminho como o daemon o entende, inclusive o
    `/run/desktop/mnt/host/...` do Docker Desktop, que serve de origem de
    bind mount. Fora de contêiner devolve None.
    """
    root = (root if root is not None else container_root()).rstrip("/")
    if not root:
        return None
    try:
        me = client.containers.get(socket.gethostname())
    except Exception as e:
        logger.debug(f"Could not inspect own container: {e}")
        return None
    for mount in me.attrs.get("Mounts") or []:
        if (mount.get("Destination") or "").rstrip("/") == root and mount.get("Type") == "bind":
            return mount.get("Source") or None
    return None


def daemon_path(path: str) -> str:
    """Translate a path seen by this process into one the Docker daemon can resolve.

    When the API itself runs in a container and creates sibling containers over
    the host socket, the `volumes=` source is resolved by the *host* daemon, so
    a container-local path like /app/storage/... does not exist on that side.
    PAINKILLER_CONTAINER_ROOT plus the host root installed with `set_host_root`
    rewrite the prefix. With either unset this returns the plain absolute path,
    which is what running directly on the host wants.
    """
    # An already-absolute POSIX path is kept verbatim: os.path.abspath would
    # rewrite it against the current drive when this runs on Windows.
    local = path if PurePosixPath(path).is_absolute() else os.path.abspath(path)
    root = container_root()
    host = host_root()

    if not root or not host:
        return local

    try:
        relative = PurePosixPath(local.replace(os.sep, "/")).relative_to(
            PurePosixPath(root.replace("\\", "/").rstrip("/"))
        )
    except ValueError:
        # Outside the mapped root: nothing to rewrite.
        return local

    # A drive letter means the host expects Windows separators.
    separator = "\\" if len(host) >= 2 and host[1] == ":" else "/"
    return host + separator + str(relative).replace("/", separator)
