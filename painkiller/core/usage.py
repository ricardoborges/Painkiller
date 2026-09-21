"""Token accounting: pull usage out of agent output and turn it into money."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

from painkiller.core.domain.models import (
    ModelPrice,
    UsageRecord,
    UsageSettings,
    UsageSource,
)

#: Nomes que cada provedor usa para os tokens de entrada. Os de cache da
#: Anthropic vêm separados de `input_tokens` e entram na soma; no Gemini o
#: `cachedContentTokenCount` já está dentro de `promptTokenCount`, então fica de fora.
_INPUT_KEYS = (
    "input_tokens",
    "prompt_tokens",
    "promptTokenCount",
    "prompt_token_count",
    "inputTokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
#: Raciocínio do Gemini é cobrado como saída mas não entra em `candidatesTokenCount`.
_OUTPUT_KEYS = (
    "output_tokens",
    "completion_tokens",
    "candidatesTokenCount",
    "candidates_token_count",
    "outputTokens",
    "thoughtsTokenCount",
    "thoughts_token_count",
)
_COST_KEYS = ("total_cost_usd", "cost_usd")

PriceLookup = Callable[[str], Optional[ModelPrice]]


def _find_usage(obj: Any, depth: int = 0) -> Optional[dict]:
    """First nested dict that carries token counters, whatever the provider."""
    if depth > 4 or not isinstance(obj, dict):
        return None
    if any(isinstance(obj.get(k), (int, float)) for k in _INPUT_KEYS + _OUTPUT_KEYS):
        return obj
    for key in ("usage", "usage_metadata", "usageMetadata", "result"):
        found = _find_usage(obj.get(key), depth + 1)
        if found is not None:
            return found
    return None


def _find_cost(obj: Any, depth: int = 0) -> Optional[float]:
    if depth > 3 or not isinstance(obj, dict):
        return None
    for key in _COST_KEYS:
        value = obj.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return _find_cost(obj.get("result"), depth + 1)


def parse_agent_usage(raw: dict) -> Optional[tuple[int, int, Optional[float], str]]:
    """Read (input, output, reported cost, model) from a turn-closing agent event.

    Tolera o envelope do Antigravity CLI (`result.usage…`) e o do Claude Code
    (`usage` + `total_cost_usd` no topo). Devolve None quando o evento não traz
    contagem nenhuma — nesse caso não há o que registrar.
    """
    usage = _find_usage(raw)
    cost = _find_cost(raw)
    if usage is None and cost is None:
        return None
    usage = usage or {}
    input_tokens = sum(int(usage.get(k) or 0) for k in _INPUT_KEYS)
    output_tokens = sum(int(usage.get(k) or 0) for k in _OUTPUT_KEYS)
    result = raw.get("result") if isinstance(raw.get("result"), dict) else {}
    model = str(raw.get("model") or result.get("model") or "")
    return input_tokens, output_tokens, cost, model


_AIDER_TOKENS = re.compile(r"Tokens:\s*([\d.,]+[kKmM]?)\s*sent.*?([\d.,]+[kKmM]?)\s*received", re.I)
_AIDER_COST = re.compile(r"Cost:\s*\$([\d.,]+)\s*message", re.I)
_AIDER_MODEL = re.compile(r"^(?:Main model|Model):\s*(\S+)", re.I | re.M)


def _count(text: str) -> int:
    text = text.replace(",", "").strip()
    scale = 1
    if text[-1:].lower() == "k":
        scale, text = 1_000, text[:-1]
    elif text[-1:].lower() == "m":
        scale, text = 1_000_000, text[:-1]
    try:
        return int(float(text) * scale)
    except ValueError:
        return 0


def parse_aider_usage(logs: str) -> Optional[tuple[int, int, Optional[float], str]]:
    """Sum the `Tokens: … sent, … received. Cost: $… message` lines Aider prints.

    Cada linha é uma chamada ao modelo; somamos todas. O custo por mensagem vem
    da tabela do LiteLLM embutida no Aider, então fica None se nenhuma linha
    trouxer `Cost:`.
    """
    input_tokens = output_tokens = 0
    cost: Optional[float] = None
    found = False
    for line in (logs or "").splitlines():
        match = _AIDER_TOKENS.search(line)
        if not match:
            continue
        found = True
        input_tokens += _count(match.group(1))
        output_tokens += _count(match.group(2))
        cost_match = _AIDER_COST.search(line)
        if cost_match:
            cost = (cost or 0.0) + float(cost_match.group(1).replace(",", ""))
    if not found:
        return None
    model_match = _AIDER_MODEL.search(logs)
    return input_tokens, output_tokens, cost, model_match.group(1) if model_match else ""


def _model_keys(model: str) -> list[str]:
    """`gemini/gemini-3.8-flash` também casa com um preço cadastrado como `gemini-3.8-flash`."""
    keys = [model]
    if "/" in model:
        keys.append(model.split("/", 1)[1])
        keys.append(model.rsplit("/", 1)[1])
    return keys


def resolve_price(
    model: str,
    settings: UsageSettings,
    fallback: Optional[PriceLookup] = None,
) -> tuple[Optional[ModelPrice], str]:
    """Price for a model and where it came from: "settings", "catalog" or "none"."""
    for key in _model_keys(model):
        if key in settings.prices:
            return settings.prices[key], "settings"
    if fallback and model:
        price = fallback(model)
        if price is not None:
            return price, "catalog"
    return None, "none"


def record_cost(
    record: UsageRecord,
    settings: UsageSettings,
    fallback: Optional[PriceLookup] = None,
) -> Optional[float]:
    """USD cost of one record. None means we have tokens but no way to price them.

    O preço cadastrado pelo analista vence, porque é o contrato dele; depois o
    custo que a ferramenta reportou; por último o catálogo do LiteLLM.
    """
    price, _ = resolve_price(record.model, settings, None)
    if price is None and record.reported_cost_usd is not None:
        return record.reported_cost_usd
    if price is None:
        price, _ = resolve_price(record.model, settings, fallback)
    if price is None:
        return None
    return (
        record.input_tokens * price.input_per_mtok + record.output_tokens * price.output_per_mtok
    ) / 1_000_000


def _bucket() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0, "unpriced_calls": 0}


def _add(bucket: dict, record: UsageRecord, cost: Optional[float]) -> None:
    bucket["input_tokens"] += record.input_tokens
    bucket["output_tokens"] += record.output_tokens
    bucket["calls"] += 1
    if cost is None:
        bucket["unpriced_calls"] += 1
    else:
        bucket["cost_usd"] += cost


def summarize(
    records: Iterable[UsageRecord],
    settings: UsageSettings,
    fallback: Optional[PriceLookup] = None,
    budget_usd: Optional[float] = None,
    days: int = 30,
    now: Optional[datetime] = None,
) -> dict:
    """Aggregate one project's ledger into totals, budget position and breakdowns."""
    now = now or datetime.now(timezone.utc)
    totals = _bucket()
    by_source: dict[str, dict] = {s.value: _bucket() for s in UsageSource}
    by_model: dict[str, dict] = {}

    first_day = (now - timedelta(days=days - 1)).date()
    daily: dict[str, dict] = {}
    for offset in range(days):
        day = (first_day + timedelta(days=offset)).isoformat()
        daily[day] = {"date": day, "cost_usd": 0.0, "tokens": 0}

    for record in records:
        cost = record_cost(record, settings, fallback)
        _add(totals, record, cost)
        _add(by_source[record.source.value], record, cost)
        _add(by_model.setdefault(record.model or "", _bucket()), record, cost)

        created = record.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day = created.date().isoformat()
        if day in daily:
            daily[day]["cost_usd"] += cost or 0.0
            daily[day]["tokens"] += record.input_tokens + record.output_tokens

    spent = totals["cost_usd"]
    budget = budget_usd
    models = []
    for model, bucket in by_model.items():
        price, origin = resolve_price(model, settings, fallback)
        models.append(
            {
                "key": model,
                **bucket,
                "price": price.model_dump() if price else None,
                "price_source": origin,
            }
        )

    return {
        "totals": {**totals, "total_tokens": totals["input_tokens"] + totals["output_tokens"]},
        "budget": {
            "budget_usd": budget,
            "spent_usd": spent,
            "remaining_usd": None if budget is None else budget - spent,
            "used_ratio": None if not budget else spent / budget,
        },
        "currency": {"local": settings.local_currency, "exchange_rate": settings.exchange_rate},
        "by_source": [{"key": k, **v} for k, v in by_source.items()],
        "by_model": sorted(models, key=lambda m: (-m["cost_usd"], -m["input_tokens"])),
        "daily": list(daily.values()),
    }
