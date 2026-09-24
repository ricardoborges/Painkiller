"""Remaining-credit lookups for the providers that actually expose one."""

import asyncio
from typing import Optional

import httpx

#: Provedores que o Painkiller conhece. Só DeepSeek e OpenRouter têm endpoint
#: público de saldo; para os demais o crédito disponível só pode vir do
#: orçamento cadastrado pelo analista.
PROVIDERS = {
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "gemini": "Google Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "nvidia": "NVIDIA Build",
}


async def _deepseek(client: httpx.AsyncClient, key: str) -> dict:
    res = await client.get(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    res.raise_for_status()
    infos = res.json().get("balance_infos") or []
    if not infos:
        return {"balance": None, "currency": None}
    # A DeepSeek devolve um saldo por moeda; preferimos USD quando existir.
    info = next((i for i in infos if i.get("currency") == "USD"), infos[0])
    return {"balance": float(info.get("total_balance") or 0), "currency": info.get("currency")}


async def _openrouter(client: httpx.AsyncClient, key: str) -> dict:
    res = await client.get(
        "https://openrouter.ai/api/v1/credits",
        headers={"Authorization": f"Bearer {key}"},
    )
    res.raise_for_status()
    data = res.json().get("data") or {}
    total = float(data.get("total_credits") or 0)
    used = float(data.get("total_usage") or 0)
    return {"balance": total - used, "currency": "USD"}


FETCHERS = {"deepseek": _deepseek, "openrouter": _openrouter}


async def fetch_balances(keys: dict[str, str], client: Optional[httpx.AsyncClient] = None) -> list[dict]:
    """One row per provider in `keys` ({provider: api_key}): its live balance, or why there is none."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        rows: list[dict] = []
        pending = []
        for provider_id, key in keys.items():
            key = (key or "").strip()
            if not key or provider_id not in PROVIDERS:
                continue
            row = {
                "provider": provider_id,
                "name": PROVIDERS[provider_id],
                "supported": provider_id in FETCHERS,
                "balance": None,
                "currency": None,
                "error": None,
            }
            rows.append(row)
            if row["supported"]:
                pending.append((row, FETCHERS[provider_id](client, key)))

        results = await asyncio.gather(*(coro for _, coro in pending), return_exceptions=True)
        for (row, _), result in zip(pending, results):
            if isinstance(result, Exception):
                row["error"] = f"Não foi possível consultar o saldo: {result}"
            else:
                row.update(result)
        return rows
    finally:
        if own_client:
            await client.aclose()


#: Chamadas baratas e autenticadas que só respondem 2xx a uma chave válida.
_VALIDATION_REQUESTS = {
    "deepseek": lambda key: ("https://api.deepseek.com/user/balance", {"Authorization": f"Bearer {key}"}),
    "gemini": lambda key: ("https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key}),
}


async def validate_key(provider: str, key: str, client: Optional[httpx.AsyncClient] = None) -> dict:
    """Ask the provider whether the key is accepted.

    Devolve {valid: True|False|None, detail}. None = não deu para saber (rede,
    provedor fora): quem chama não deve bloquear o analista por isso.
    """
    build = _VALIDATION_REQUESTS.get(provider)
    if build is None:
        return {"valid": None, "detail": f"Validação não suportada para {provider}."}
    if not (key or "").strip():
        return {"valid": False, "detail": "Informe a chave de API."}
    url, headers = build(key.strip())
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        res = await client.get(url, headers=headers)
    except httpx.HTTPError as e:
        return {"valid": None, "detail": f"Não foi possível falar com o provedor: {e}"}
    finally:
        if own_client:
            await client.aclose()
    if res.status_code in (400, 401, 403):
        return {"valid": False, "detail": f"{PROVIDERS.get(provider, provider)} recusou a chave (HTTP {res.status_code})."}
    if res.is_success:
        return {"valid": True, "detail": None}
    return {"valid": None, "detail": f"O provedor respondeu HTTP {res.status_code}; a chave não foi confirmada."}
