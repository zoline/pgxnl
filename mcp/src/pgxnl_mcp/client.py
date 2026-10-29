"""pgxnl HTTP API 호출. MCP 도구(server.py)는 이 함수들을 감싸기만 한다.

모든 호출은 X-API-Key 로 인증한다 — pgxnl 의 읽기 전용·비용 상한·감사 기록이 그대로
적용되도록, DB 에 직접 붙지 않고 반드시 pgxnl API 를 거친다.
"""
from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

# ask 는 질문 보강·스키마 링킹·ReAct·검증·실행을 다 거친다 — 실측 15~60초, 길면 2분 넘게.
ASK_TIMEOUT_SECONDS = 300.0
DEFAULT_TIMEOUT_SECONDS = 60.0


class PgxnlError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    url: str
    api_key: str
    verify_ssl: bool = True

    @classmethod
    def from_env(cls) -> Config:
        url = os.environ.get("PGXNL_URL", "").rstrip("/")
        key = os.environ.get("PGXNL_API_KEY", "")
        if not url or not key:
            raise PgxnlError("PGXNL_URL 과 PGXNL_API_KEY 환경변수가 필요합니다")
        verify = os.environ.get("PGXNL_VERIFY_SSL", "true").lower() not in ("0", "false", "no")
        return cls(url=url, api_key=key, verify_ssl=verify)


def _client(cfg: Config, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=cfg.url, headers={"X-API-Key": cfg.api_key}, verify=cfg.verify_ssl, timeout=timeout,
    )


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    if resp.status_code == 401:
        detail = f"인증 실패 — PGXNL_API_KEY 를 확인하세요 ({detail})"
    raise PgxnlError(f"pgxnl {resp.status_code}: {detail}")


async def get(cfg: Config, path: str, params: dict[str, Any] | None = None) -> Any:
    async with _client(cfg) as c:
        resp = await c.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
    _raise_for(resp)
    return resp.json()


async def post(cfg: Config, path: str, body: dict[str, Any]) -> Any:
    async with _client(cfg) as c:
        resp = await c.post(path, json=body)
    _raise_for(resp)
    return resp.json()


def parse_sse_lines(lines: list[str]) -> tuple[str | None, str]:
    """SSE 이벤트 한 덩어리(빈 줄로 끝나는 줄들)를 (event, data) 로."""
    event, data = None, []
    for line in lines:
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    return event, "\n".join(data)


async def ask(
    cfg: Config, body: dict[str, Any], on_status: Callable[[str], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    """POST /api/analyze — SSE 로 진행 상황(status)을 받다가 answer 하나를 돌려준다."""
    async with _client(cfg, ASK_TIMEOUT_SECONDS) as c:
        async with c.stream("POST", "/api/analyze", json=body) as resp:
            if resp.status_code >= 400:
                await resp.aread()
                _raise_for(resp)
            block: list[str] = []
            async for line in resp.aiter_lines():
                if line.strip():
                    block.append(line)
                    continue
                if not block:
                    continue
                event, data = parse_sse_lines(block)
                block = []
                payload = json.loads(data) if data else {}
                if event == "status" and on_status is not None:
                    await on_status(payload.get("message", ""))
                elif event == "answer":
                    return payload
                elif event == "error":
                    raise PgxnlError(payload.get("message", "알 수 없는 오류"))
    raise PgxnlError("pgxnl 이 답 없이 스트림을 닫았습니다")
