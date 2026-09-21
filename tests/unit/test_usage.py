"""Tests for token accounting: parsing, pricing, the ledger and the usage routes."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from painkiller.adapters.issue_trackers.sqlite_tracker import SQLiteIssueTracker
from painkiller.api.server import create_app
from painkiller.core.domain.models import (
    AgentEvent,
    AgentEventType,
    ExecutionResult,
    ModelPrice,
    Project,
    Task,
    UsageRecord,
    UsageSettings,
    UsageSource,
)
from painkiller.core.usage import (
    parse_agent_usage,
    parse_aider_usage,
    record_cost,
    summarize,
)
from painkiller.engine.analysis import AnalysisOrchestrator, AnalysisRun
from painkiller.engine.orchestrator import PainkillerOrchestrator
from painkiller.core.domain.models import AnalysisSession


def test_parse_claude_code_result():
    raw = {
        "type": "result",
        "total_cost_usd": 0.0421,
        "usage": {
            "input_tokens": 1200,
            "cache_read_input_tokens": 800,
            "output_tokens": 300,
        },
    }
    assert parse_agent_usage(raw) == (2000, 300, 0.0421, "")


def test_parse_gemini_style_result_nested_under_result():
    raw = {
        "event": "result",
        "result": {
            "response": "ok",
            "model": "gemini-3.8-flash",
            "usage_metadata": {
                "promptTokenCount": 5000,
                "candidatesTokenCount": 400,
                "thoughtsTokenCount": 100,
                "cachedContentTokenCount": 2000,
            },
        },
    }
    assert parse_agent_usage(raw) == (5000, 500, None, "gemini-3.8-flash")


def test_parse_result_without_usage_is_ignored():
    assert parse_agent_usage({"event": "result", "result": {"response": "oi"}}) is None


def test_parse_aider_logs_sums_every_call():
    logs = "\n".join(
        [
            "Aider v0.86.0",
            "Main model: gemini/gemini-3.8-flash with diff edit format",
            "Tokens: 12k sent, 1.2k received. Cost: $0.04 message, $0.04 session.",
            "Applied edit to app.py",
            "Tokens: 2,500 sent, 1.1k cache hit, 150 received. Cost: $0.01 message, $0.05 session.",
        ]
    )
    assert parse_aider_usage(logs) == (14_500, 1_350, pytest.approx(0.05), "gemini/gemini-3.8-flash")


def test_parse_aider_logs_without_token_lines():
    assert parse_aider_usage("Container execution error: boom") is None


def test_record_cost_prefers_analyst_price_then_reported_then_catalog():
    record = UsageRecord(
        source=UsageSource.TASK,
        model="gemini/gemini-3.8-flash",
        input_tokens=1_000_000,
        output_tokens=500_000,
        reported_cost_usd=9.99,
    )
    priced = UsageSettings(prices={"gemini-3.8-flash": ModelPrice(input_per_mtok=0.5, output_per_mtok=3)})
    assert record_cost(record, priced) == pytest.approx(2.0)
    assert record_cost(record, UsageSettings()) == pytest.approx(9.99)

    unreported = record.model_copy(update={"reported_cost_usd": None})
    catalog = lambda model: ModelPrice(input_per_mtok=1, output_per_mtok=2)
    assert record_cost(unreported, UsageSettings(), catalog) == pytest.approx(2.0)
    assert record_cost(unreported, UsageSettings()) is None


def test_summarize_budget_breakdowns_and_unpriced():
    now = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
    settings = UsageSettings(prices={"m1": ModelPrice(input_per_mtok=1, output_per_mtok=1)})
    records = [
        UsageRecord(source=UsageSource.ANALYSIS, model="m1", project_id="p1",
                    input_tokens=2_000_000, output_tokens=1_000_000, created_at=now),
        UsageRecord(source=UsageSource.TASK, model="m1", project_id="p1",
                    input_tokens=1_000_000, output_tokens=0, created_at=now),
        UsageRecord(source=UsageSource.TASK, model="desconhecido", project_id="p1",
                    input_tokens=10, output_tokens=5, created_at=now),
    ]
    summary = summarize(records, settings, budget_usd=10, now=now)

    assert summary["totals"]["cost_usd"] == pytest.approx(4.0)
    assert summary["totals"]["total_tokens"] == 4_000_015
    assert summary["totals"]["unpriced_calls"] == 1
    assert summary["budget"]["remaining_usd"] == pytest.approx(6.0)
    assert summary["budget"]["used_ratio"] == pytest.approx(0.4)

    sources = {s["key"]: s for s in summary["by_source"]}
    assert sources["ANALYSIS"]["cost_usd"] == pytest.approx(3.0)
    assert sources["LLM"]["calls"] == 0

    models = {m["key"]: m for m in summary["by_model"]}
    assert models["m1"]["price_source"] == "settings"
    assert models["desconhecido"]["price_source"] == "none"

    assert len(summary["daily"]) == 30
    assert summary["daily"][-1]["cost_usd"] == pytest.approx(4.0)


async def test_ledger_roundtrip(tmp_path):
    ledger = SQLiteIssueTracker(db_url=f"sqlite+aiosqlite:///{tmp_path / 'u.db'}")
    await ledger.init_db()
    try:
        assert await ledger.get_usage_settings() == UsageSettings()

        saved = await ledger.record_usage(
            UsageRecord(source=UsageSource.TASK, model="m", project_id="p1", input_tokens=7)
        )
        assert saved.id.startswith("usage-")
        await ledger.record_usage(UsageRecord(source=UsageSource.LLM, model="m", output_tokens=3))

        assert len(await ledger.list_usage()) == 2
        only_p1 = await ledger.list_usage(project_id="p1")
        assert [r.input_tokens for r in only_p1] == [7]

        settings = UsageSettings(exchange_rate=5.4, prices={"m": ModelPrice(input_per_mtok=1)})
        await ledger.save_usage_settings(settings)
        await ledger.save_usage_settings(settings)
        assert await ledger.get_usage_settings() == settings

        # Orçamento é por projeto: um não enxerga o do outro, e None apaga.
        assert await ledger.get_project_budget("p1") is None
        await ledger.save_project_budget("p1", 25)
        await ledger.save_project_budget("p1", 30)
        assert await ledger.get_project_budget("p1") == 30
        assert await ledger.get_project_budget("p2") is None
        await ledger.save_project_budget("p1", None)
        assert await ledger.get_project_budget("p1") is None
    finally:
        await ledger.close()


async def test_dispatch_records_aider_usage_even_when_the_run_fails():
    tracker, sandbox, git, usage = AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock()
    tracker.get_task.return_value = Task(id="t1", project_id="p1", title="T", description="D")
    tracker.get_project.return_value = Project(id="p1", name="App", repo_path="/repo")
    sandbox.run_task.return_value = ExecutionResult(
        exit_code=1,
        logs="Model: openai/kimi\nTokens: 3k sent, 200 received. Cost: $0.02 message, $0.02 session.",
    )

    orchestrator = PainkillerOrchestrator(tracker=tracker, sandbox=sandbox, git=git, usage=usage)
    await orchestrator.dispatch_task("t1")

    record = usage.record_usage.call_args.args[0]
    assert (record.source, record.task_id, record.project_id) == (UsageSource.TASK, "t1", "p1")
    assert (record.input_tokens, record.output_tokens, record.model) == (3000, 200, "openai/kimi")
    assert record.reported_cost_usd == pytest.approx(0.02)


async def test_analysis_result_is_booked_once_even_after_rewind():
    usage = AsyncMock()
    agent = AsyncMock()
    result = AgentEvent(
        type=AgentEventType.RESULT,
        raw={"event": "result", "result": {"usage": {"input_tokens": 10, "output_tokens": 4}}},
    )
    init = AgentEvent(type=AgentEventType.SYSTEM, raw={"event": "init", "init": {"model": "gemini-x"}})

    async def stream(_):
        for event in (init, result):
            yield event

    agent.stream = stream
    orchestrator = AnalysisOrchestrator(agent=agent, tracker=AsyncMock(), usage=usage)
    run = AnalysisRun(AnalysisSession(id="s1", project_id="p1"), repo_path="/repo")

    await orchestrator._pump(run)
    assert usage.record_usage.call_count == 1
    record = usage.record_usage.call_args.args[0]
    assert (record.model, record.session_id, record.input_tokens) == ("gemini-x", "s1", 10)

    # Religar o pump num contêiner vivo relê o log inteiro: nada novo a cobrar.
    orchestrator._rewind(run)
    await orchestrator._pump(run)
    assert usage.record_usage.call_count == 1


@pytest.fixture
async def client(tmp_path):
    app = create_app(db_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    app.state.price_lookup = lambda model: None

    async def balances():
        return [{"provider": "deepseek", "name": "DeepSeek", "supported": True,
                 "balance": 12.5, "currency": "USD", "error": None}]

    app.state.balance_lookup = balances
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c, app


async def test_usage_routes_are_scoped_to_the_project(client):
    c, app = client
    tracker = app.state.tracker
    mine = await tracker.create_project(name="App", repo_path="/tmp/app")
    other = await tracker.create_project(name="Outro", repo_path="/tmp/outro")
    base = f"/api/projects/{mine.id}/usage"

    empty = (await c.get(base)).json()
    assert empty["totals"]["calls"] == 0
    assert empty["budget"]["remaining_usd"] is None

    for project_id in (mine.id, other.id):
        await app.state.usage.record_usage(
            UsageRecord(source=UsageSource.ANALYSIS, model="gemini-3.8-flash", project_id=project_id,
                        input_tokens=1_000_000, output_tokens=1_000_000)
        )

    res = await c.put(
        "/api/usage/settings",
        json={"exchange_rate": 5.5, "local_currency": "brl",
              "prices": {"gemini-3.8-flash": {"input_per_mtok": 0.5, "output_per_mtok": 2.5}}},
    )
    assert res.status_code == 200
    assert res.json()["local_currency"] == "BRL"
    assert (await c.put(f"{base}/budget", json={"budget_usd": 20})).status_code == 200

    summary = (await c.get(base)).json()
    assert summary["totals"]["cost_usd"] == pytest.approx(3.0)
    assert summary["budget"]["remaining_usd"] == pytest.approx(17.0)
    assert summary["currency"] == {"local": "BRL", "exchange_rate": 5.5}

    # O outro projeto gastou o mesmo, mas não herda o orçamento.
    theirs = (await c.get(f"/api/projects/{other.id}/usage")).json()
    assert theirs["totals"]["cost_usd"] == pytest.approx(3.0)
    assert theirs["budget"]["budget_usd"] is None

    records = (await c.get(f"{base}/records")).json()
    assert [r["project_id"] for r in records] == [mine.id]
    assert records[0]["cost_usd"] == pytest.approx(3.0)

    assert (await c.put(f"{base}/budget", json={"budget_usd": -1})).status_code == 422
    assert (await c.get("/api/projects/nao-existe/usage")).status_code == 404
    assert (await c.get("/api/usage")).status_code == 404
    assert (await c.get("/api/usage/balances")).json()[0]["balance"] == 12.5


async def test_fetch_balances_only_for_configured_providers(monkeypatch):
    import httpx
    from painkiller.adapters.llm.balance import PROVIDERS, fetch_balances

    for _, _, names in PROVIDERS:
        for name in names:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def handler(request: httpx.Request) -> httpx.Response:
        if "deepseek" in request.url.host:
            return httpx.Response(200, json={"balance_infos": [
                {"currency": "CNY", "total_balance": "70.00"},
                {"currency": "USD", "total_balance": "9.50"},
            ]})
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = {r["provider"]: r for r in await fetch_balances(client)}

    assert set(rows) == {"deepseek", "openrouter", "gemini"}
    assert (rows["deepseek"]["balance"], rows["deepseek"]["currency"]) == (9.5, "USD")
    assert rows["openrouter"]["error"]
    assert rows["gemini"]["supported"] is False and rows["gemini"]["balance"] is None
