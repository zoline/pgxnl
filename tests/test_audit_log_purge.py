"""감사 로그 기간 지정 삭제 (2026-10-14)."""
from __future__ import annotations

import asyncio

from pgxnl.api import routes_admin
from pgxnl.api.state import state
from pgxnl.auth.dependencies import CurrentUser


class _Pool:
    def __init__(self):
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        return 7

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "DELETE 7"


def test_where_절(monkeypatch=None) -> None:
    assert routes_admin._audit_purge_where(1, None) == ("created_at < now() - make_interval(days => $1)", [1])
    where, params = routes_admin._audit_purge_where(0, "BIRD")
    assert where.endswith("AND target_name = $2") and params == [0, "BIRD"]


def test_삭제는_건수를_돌려준다(monkeypatch) -> None:
    pool = _Pool()
    monkeypatch.setattr(state, "system_pool", pool, raising=False)
    admin = CurrentUser(id=1, username="pgxnl", role="admin")
    out = asyncio.run(routes_admin.audit_log_purge(older_than_days=1, target="BIRD", admin=admin))
    assert out == {"deleted": 7}
    sql, args = pool.calls[-1]
    assert sql.startswith("DELETE FROM pgxnl_audit_log WHERE") and args == (1, "BIRD")
    assert asyncio.run(routes_admin.audit_log_purge_count(older_than_days=1, target=None)) == {"count": 7}
