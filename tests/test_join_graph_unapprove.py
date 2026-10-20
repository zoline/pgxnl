"""JOIN 그래프 승인 해제 — 삭제하지 않고 대기 후보로 되돌린다 (2026-10-12)."""
from __future__ import annotations

from pgxnl.agent.discovery.graph import unapprove_edges


class _Pool:
    def __init__(self):
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return [{"id": i} for i in args[1]]


async def test_승인을_해제하고_삭제하지_않는다() -> None:
    pool = _Pool()
    n = await unapprove_edges(pool, "BIRD", [6935])
    sql, args = pool.calls[0]
    assert n == 1 and args == ("BIRD", [6935])
    assert sql.lstrip().upper().startswith("UPDATE") and "reviewed = false" in sql
    assert "DELETE" not in sql.upper()
