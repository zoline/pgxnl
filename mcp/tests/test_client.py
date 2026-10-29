"""pgxnl API 호출 계층 테스트 — 실제 서버 없이 httpx MockTransport 로."""
from __future__ import annotations

import json

import httpx
import pytest

from pgxnl_mcp import client, server
from pgxnl_mcp.client import Config, PgxnlError

CFG = Config(url="https://pgxnl.example.com", api_key="k")


def _sse(*events: tuple[str, dict]) -> bytes:
    return "".join(
        f"event: {e}\r\ndata: {json.dumps(d, ensure_ascii=False)}\r\n\r\n" for e, d in events
    ).encode()


@pytest.fixture
def mock(monkeypatch):
    """핸들러를 꽂으면 client._client 가 그 transport 를 쓴다."""
    def install(handler):
        def make(cfg, timeout=client.DEFAULT_TIMEOUT_SECONDS):
            return httpx.AsyncClient(
                base_url=cfg.url, headers={"X-API-Key": cfg.api_key},
                transport=httpx.MockTransport(handler),
            )
        monkeypatch.setattr(client, "_client", make)
    return install


async def test_ask_forwards_status_and_returns_answer(mock):
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["key"] = req.headers["X-API-Key"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=_sse(
            ("status", {"message": "스키마 링킹 중..."}),
            ("answer", {"answer": "", "sql_steps": [{"sql": "SELECT 1"}], "rows": [{"a": 1}]}),
        ))

    mock(handler)
    statuses: list[str] = []

    async def on_status(m):
        statuses.append(m)

    r = await client.ask(CFG, {"target": "t", "question": "q", "summarize": False}, on_status)
    assert r["rows"] == [{"a": 1}]
    assert statuses == ["스키마 링킹 중..."]
    assert seen["key"] == "k" and seen["body"]["summarize"] is False


async def test_ask_error_event_raises(mock):
    mock(lambda req: httpx.Response(200, content=_sse(("error", {"message": "LLM 타임아웃"}))))
    with pytest.raises(PgxnlError, match="LLM 타임아웃"):
        await client.ask(CFG, {})


async def test_unauthorized_is_explained(mock):
    mock(lambda req: httpx.Response(401, json={"detail": "invalid api key"}))
    with pytest.raises(PgxnlError, match="PGXNL_API_KEY"):
        await client.get(CFG, "/api/targets")


async def test_none_params_are_dropped(mock):
    seen = {}

    def handler(req):
        seen["q"] = dict(req.url.params)
        return httpx.Response(200, json={})

    mock(handler)
    await client.get(CFG, "/x", {"a": "1", "b": None})
    assert seen["q"] == {"a": "1"}


def test_cap_rows_by_count_and_chars(monkeypatch):
    monkeypatch.setattr(server, "MAX_ROWS", 3)
    r = server._cap_rows([{"i": i} for i in range(10)])
    assert r == {"row_count": 10, "rows": [{"i": 0}, {"i": 1}, {"i": 2}], "truncated": True}

    monkeypatch.setattr(server, "MAX_ROWS", 50)
    monkeypatch.setattr(server, "MAX_CHARS", 100)
    wide = [{"t": "x" * 40} for _ in range(10)]
    r = server._cap_rows(wide)
    assert r["truncated"] and 0 < len(r["rows"]) < 10
    assert len(json.dumps(r["rows"])) <= 100


def test_cap_rows_none():
    assert server._cap_rows(None) == {"row_count": 0, "rows": [], "truncated": False}


def test_config_requires_url_and_key(monkeypatch):
    monkeypatch.delenv("PGXNL_URL", raising=False)
    monkeypatch.delenv("PGXNL_API_KEY", raising=False)
    with pytest.raises(PgxnlError):
        Config.from_env()
    monkeypatch.setenv("PGXNL_URL", "https://h/")
    monkeypatch.setenv("PGXNL_API_KEY", "k")
    monkeypatch.setenv("PGXNL_VERIFY_SSL", "false")
    c = Config.from_env()
    assert c.url == "https://h" and c.verify_ssl is False
