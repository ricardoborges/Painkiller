"""Usage routes: tokens and money spent by each project, and the price lists.

O admin define o preço por harness e modelo; cada projeto herda o do seu
harness e pode sobrescrever modelo a modelo.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from painkiller.api.security import require_admin, visible_project
from painkiller.core.domain.models import (
    HarnessType,
    ModelPrice,
    UsageSettings,
    harness_model,
    key_provider,
)
from painkiller.core.i18n import translate
from painkiller.core.usage import project_pricing, record_cost, summarize

router = APIRouter(prefix="/api/usage", tags=["usage"])
project_router = APIRouter(prefix="/api/projects/{project_id}/usage", tags=["usage"])


class UsageSettingsRequest(BaseModel):
    exchange_rate: Optional[float] = Field(default=None, gt=0)
    local_currency: str = "BRL"
    prices: dict[str, ModelPrice] = Field(default_factory=dict)
    harness_prices: dict[str, dict[str, ModelPrice]] = Field(default_factory=dict)


class ProjectPricesRequest(BaseModel):
    prices: dict[str, ModelPrice] = Field(default_factory=dict)


class ProjectBudgetRequest(BaseModel):
    budget_usd: Optional[float] = Field(default=None, ge=0)


async def _require_project(request: Request, project_id: str) -> None:
    await visible_project(request, project_id)


def _clean_prices(prices: dict[str, ModelPrice]) -> dict[str, ModelPrice]:
    return {k.strip(): v for k, v in prices.items() if k.strip()}


async def _project_pricing(request: Request, project_id: str):
    """Shared settings as this project sees them, plus its own overrides."""
    project = await visible_project(request, project_id)
    ledger = request.app.state.usage
    settings = project_pricing(await ledger.get_usage_settings(), project.harness)
    return settings, await ledger.get_project_prices(project_id)


@project_router.get("")
async def get_project_usage(project_id: str, request: Request):
    settings, overrides = await _project_pricing(request, project_id)
    ledger = request.app.state.usage
    return summarize(
        await ledger.list_usage(project_id=project_id),
        settings,
        fallback=request.app.state.price_lookup,
        budget_usd=await ledger.get_project_budget(project_id),
        overrides=overrides,
    )


@project_router.get("/records")
async def list_project_usage_records(project_id: str, request: Request, limit: int = 50):
    settings, overrides = await _project_pricing(request, project_id)
    ledger = request.app.state.usage
    records = await ledger.list_usage(project_id=project_id)
    recent = records[::-1][: max(1, min(limit, 500))]
    return [
        {
            **r.model_dump(mode="json"),
            "cost_usd": record_cost(r, settings, request.app.state.price_lookup, overrides),
        }
        for r in recent
    ]


async def _project_prices_view(request: Request, project_id: str) -> dict:
    project = await visible_project(request, project_id)
    ledger = request.app.state.usage
    settings = await ledger.get_usage_settings()
    harness = getattr(project.harness, "value", project.harness)
    # Herdado mostra só o que vale para este harness (a lista dele e a sem
    # harness); preços de outros harnesses ainda contam no custo, como reserva.
    inherited = {**settings.prices, **settings.harness_prices.get(harness, {})}
    return {
        "harness": harness,
        "model": harness_model(project.harness, project.model),
        "inherited": {m: p.model_dump() for m, p in inherited.items()},
        "overrides": {
            m: p.model_dump() for m, p in (await ledger.get_project_prices(project_id)).items()
        },
    }


@project_router.get("/prices")
async def get_project_prices(project_id: str, request: Request):
    """Prices this project inherits from the admin, and the ones it overrides."""
    return await _project_prices_view(request, project_id)


@project_router.put("/prices")
async def save_project_prices(project_id: str, body: ProjectPricesRequest, request: Request):
    await _require_project(request, project_id)
    await request.app.state.usage.save_project_prices(project_id, _clean_prices(body.prices))
    return await _project_prices_view(request, project_id)


@project_router.put("/budget")
async def save_project_budget(
    project_id: str, body: ProjectBudgetRequest, request: Request
) -> ProjectBudgetRequest:
    await _require_project(request, project_id)
    await request.app.state.usage.save_project_budget(project_id, body.budget_usd)
    return body


@router.get("/settings")
async def get_usage_settings(request: Request) -> UsageSettings:
    return await request.app.state.usage.get_usage_settings()


@router.put("/settings", dependencies=[Depends(require_admin)])
async def save_usage_settings(body: UsageSettingsRequest, request: Request) -> UsageSettings:
    currency = body.local_currency.strip().upper()
    if not currency or len(currency) > 5:
        raise HTTPException(status_code=400, detail="Moeda local inválida. Use um código como BRL.")
    known = {h.value for h in HarnessType}
    if set(body.harness_prices) - known:
        raise HTTPException(status_code=400, detail="Harness desconhecido na tabela de preços.")
    settings = UsageSettings(
        exchange_rate=body.exchange_rate,
        local_currency=currency,
        prices=_clean_prices(body.prices),
        harness_prices={
            h: cleaned for h, table in body.harness_prices.items() if (cleaned := _clean_prices(table))
        },
    )
    return await request.app.state.usage.save_usage_settings(settings)


@project_router.get("/balances")
async def get_project_balances(project_id: str, request: Request):
    """Live balance of the provider account behind the project's own key."""
    project = await visible_project(request, project_id)
    if not project.api_key:
        return []
    rows = await request.app.state.balance_lookup({key_provider(project.harness): project.api_key})
    return [{**row, "error": translate(row.get("error"))} for row in rows]
