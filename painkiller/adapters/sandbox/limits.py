"""Resource limits for the containers that run agent code."""

import os
from typing import Any

#: Processos e threads por contêiner. Folgado para Gradle + Node (algumas
#: centenas de threads), mas barra uma fork bomb antes de ela derrubar o host.
DEFAULT_PIDS_LIMIT = 4096


def container_limits() -> dict[str, Any]:
    """Keyword arguments for ``containers.run`` that cap an agent container.

    `PAINKILLER_AGENT_PIDS_LIMIT` troca o teto de processos (0 desliga);
    `PAINKILLER_AGENT_MEMORY` (ex.: "6g") liga um teto de memória, sem padrão
    porque o Gradle de um build Android precisa de alguns GB e o valor certo
    depende da máquina.
    """
    limits: dict[str, Any] = {}
    try:
        pids = int(os.environ.get("PAINKILLER_AGENT_PIDS_LIMIT", "") or DEFAULT_PIDS_LIMIT)
    except ValueError:
        pids = DEFAULT_PIDS_LIMIT
    if pids > 0:
        limits["pids_limit"] = pids
    memory = (os.environ.get("PAINKILLER_AGENT_MEMORY") or "").strip()
    if memory:
        limits["mem_limit"] = memory
    return limits
