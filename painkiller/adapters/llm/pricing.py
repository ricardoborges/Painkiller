"""Model price lookup backed by LiteLLM's bundled cost catalog."""

from typing import Optional

from painkiller.core.domain.models import ModelPrice


def litellm_price(model: str) -> Optional[ModelPrice]:
    """USD per 1M tokens for `model`, or None when the catalog does not know it."""
    try:
        import litellm
    except ImportError:
        return None

    catalog = getattr(litellm, "model_cost", None) or {}
    candidates = [model]
    if "/" in model:
        candidates.append(model.rsplit("/", 1)[1])
    for key in candidates:
        entry = catalog.get(key)
        if not isinstance(entry, dict):
            continue
        input_cost = entry.get("input_cost_per_token")
        output_cost = entry.get("output_cost_per_token")
        if input_cost is None and output_cost is None:
            continue
        return ModelPrice(
            input_per_mtok=float(input_cost or 0) * 1_000_000,
            output_per_mtok=float(output_cost or 0) * 1_000_000,
        )
    return None
