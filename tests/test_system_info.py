from types import SimpleNamespace

import pgxnl.api.system_info as si


async def test_ping_target_reports_failure_without_raising():
    r = await si.ping_target("x", "postgresql://u:p@127.0.0.1:1/db", timeout=1.0)
    assert r["name"] == "x" and r["ok"] is False and r["ms"] is None and r["error"]


class _Store:
    def __init__(self, records):
        self.records = records
        self.calls = 0

    async def list_targets(self):
        self.calls += 1
        return self.records


async def test_collect_status_counts_and_caches(monkeypatch):
    async def fake_ping(name, dsn, timeout=si.PING_TIMEOUT):
        return {"name": name, "ok": name == "up", "ms": 1 if name == "up" else None, "error": None}

    monkeypatch.setattr(si, "ping_target", fake_ping)
    monkeypatch.setattr(si, "_status_cache", None)
    monkeypatch.setattr(si, "mask_dsn", lambda d: d)
    store = _Store([SimpleNamespace(name="up", dsn="d1"), SimpleNamespace(name="down", dsn="d2")])
    state = SimpleNamespace(target_store=store, system_pool=object(), llm_profile_store=None)

    s1 = await si.collect_status(state)
    assert s1["system_db"] is True
    assert s1["targets"] == {"ok": 1, "total": 2, "down": ["down"]}
    assert s1["llm"]["source"] == "env"
    await si.collect_status(state)
    assert store.calls == 1  # 30초 안의 두 번째 호출은 접속하지 않는다
    await si.collect_status(state, use_cache=False)
    assert store.calls == 2
