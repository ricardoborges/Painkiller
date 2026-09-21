"""Remaining-credit lookups for the providers that actually expose one."""

import asyncio
import os
from typing import Optional

import httpx

#: Provedores cujas chaves o Painkiller repassa aos agentes. Só DeepSeek e
#: OpenRouter têm endpoint público de saldo; para os demais o crédito
#: disponível só pode vir do orçamento cadastrado pelo analista.
PROVIDERS = (
    ("deepseek", "DeepSeek", ("DEEPSEEK_API_KEY",)),
    ("openrouter", "OpenRouter", ("OPENROUTER_API_KEY",)),
    ("gemini", "Google Gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    ("openai", "OpenAI", ("OPENAI_API_KEY",)),
    ("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",)),
    ("nvidia", "NVIDIA Build", ("NVIDIA_API_KEY",)),
)


def _key(env_names: tuple[str, ...]) -> str:
    for name in env_names:
        value = (os.environ.get(name) or "").strip().strip('"').strip("'")
        if value:
            return value
    return ""


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


async def fetch_balances(client: Optional[httpx.AsyncClient] = None) -> list[dict]:
    """One row per configured provider: its live balance, or why there is none."""
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10.0)
    try:
        rows: list[dict] = []
        pending = []
        for provider_id, name, env_names in PROVIDERS:
            key = _key(env_names)
            if not key:
                continue
            row = {
                "provider": provider_id,
                "name": name,
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
