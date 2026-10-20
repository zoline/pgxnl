"""디버그 '필터 값 검증'이 죽지 않는다 (2026-10-12).

_filter_literals 가 (값, 컬럼, 패턴 여부) 세 개를 주는데 두 개로 풀어 매번 ValueError 로 죽었다.
"""
from __future__ import annotations

import asyncio
import logging

from pgxnl.agent.orchestrator import Orchestrator
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser
from pgxnl.settings import Settings


class _Conn:
    def __init__(self):
        self.queries: list[tuple[str, list]] = []

    async def execute_readonly(self, sql, params=None, **_k):
        self.queries.append((sql, params))
        return [{"n": 7}]


def _orc() -> tuple[Orchestrator, _Conn]:
    conn = _Conn()
    orc = Orchestrator(conn, Settings(), llm=None, parser=AntlrPostgresParser(), target_name="T")

    async def resolve(_t, col, _s):
        return col
    orc._resolve_column = resolve
    return orc, conn


def test_값_검증을_찍고_패턴은_건너뛴다(caplog) -> None:
    orc, conn = _orc()
    lines: list[str] = []

    async def dbg(msg):
        lines.append(msg)

    sql = "SELECT T1.name FROM schools AS T1 WHERE T1.county = 'Alameda' AND T1.city LIKE 'Fre%'"
    with caplog.at_level(logging.WARNING):
        asyncio.run(orc._emit_filter_rationale(sql, "s", dbg))
    assert "필터 값 검증 실패" not in caplog.text   # 예전엔 여기서 ValueError
    assert len(lines) == 1 and "'Alameda'" in lines[0] and "7행" in lines[0]
    assert all("Fre%" not in str(p) for _, p in conn.queries)  # LIKE 패턴은 세지 않는다
