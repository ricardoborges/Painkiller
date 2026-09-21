"""Usage routes: tokens and money spent by each project, and the shared price list."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from painkiller.core.domain.models import ModelPrice, UsageSettings
from painkiller.core.usage import record_cost, summarize

router = APIRouter(prefix="/api/usage", tags=["usage"])
project_router = APIRouter(prefix="/api/projects/{project_id}/usage", tags=["usage"])


class UsageSettingsRequest(BaseModel):
    exchange_rate: Optional[float] = Field(default=None, gt=0)
    local_currency: str = "BRL"
    prices: dict[str, ModelPrice] = Field(default_factory=dict)


class ProjectBudgetRequest(BaseModel):
    budget_usd: Optional[float] = Field(default=None, ge=0)


async def _require_project(request: Request, project_id: str) -> None:
    if await request.app.state.tracker.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")


@project_router.get("")
async def get_project_usage(project_id: str, request: Request):
    await _require_project(request, project_id)
    ledger = request.app.state.usage
    return summarize(
        await ledger.list_usage(project_id=project_id),
        await ledger.get_usage_settings(),
        fallback=request.app.state.price_lookup,
        budget_usd=await ledger.get_project_budget(project_id),
    )


@project_router.get("/records")
async def list_project_usage_records(project_id: str, request: Request, limit: int = 50):
    await _require_project(request, project_id)
    ledger = request.app.state.usage
    records = await ledger.list_usage(project_id=project_id)
    settings = await ledger.get_usage_settings()
    recent = records[::-1][: max(1, min(limit, 500))]
    return [
        {
            **r.model_dump(mode="json"),
            "cost_usd": record_cost(r, settings, request.app.state.price_lookup),
        }
        for r in recent
    ]


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


@router.put("/settings")
async def save_usage_settings(body: UsageSettingsRequest, request: Request) -> UsageSettings:
    currency = body.local_currency.strip().upper()
    if not currency or len(currency) > 5:
        raise HTTPException(status_code=400, detail="Moeda local inválida. Use um código como BRL.")
    prices = {k.strip(): v for k, v in body.prices.items() if k.strip()}
    settings = UsageSettings(
        exchange_rate=body.exchange_rate,
        local_currency=currency,
        prices=prices,
    )
    return await request.app.state.usage.save_usage_settings(settings)


@router.get("/balances")
async def get_provider_balances(request: Request):
    return await request.app.state.balance_lookup()
