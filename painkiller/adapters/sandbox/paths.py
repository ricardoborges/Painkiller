"""Path translation between this process and the Docker daemon."""

import os
from pathlib import PurePosixPath


def daemon_path(path: str) -> str:
    """Translate a path seen by this process into one the Docker daemon can resolve.

    When the API itself runs in a container and creates sibling containers over
    the host socket, the `volumes=` source is resolved by the *host* daemon, so
    a container-local path like /app/storage/... does not exist on that side.
    Setting the PAINKILLER_CONTAINER_ROOT / PAINKILLER_HOST_ROOT pair rewrites
    the prefix. With either variable unset this returns the plain absolute path,
    which is what running directly on the host wants.
    """
    # An already-absolute POSIX path is kept verbatim: os.path.abspath would
    # rewrite it against the current drive when this runs on Windows.
    local = path if PurePosixPath(path).is_absolute() else os.path.abspath(path)
    container_root = os.environ.get("PAINKILLER_CONTAINER_ROOT", "").strip()
    host_root = os.environ.get("PAINKILLER_HOST_ROOT", "").strip().rstrip("/\\")

    if not container_root or not host_root:
        return local

    try:
        relative = PurePosixPath(local.replace(os.sep, "/")).relative_to(
            PurePosixPath(container_root.replace("\\", "/").rstrip("/"))
        )
    except ValueError:
        # Outside the mapped root: nothing to rewrite.
        return local

    # A drive letter means the host expects Windows separators.
    separator = "\\" if len(host_root) >= 2 and host_root[1] == ":" else "/"
    return host_root + separator + str(relative).replace("/", separator)
