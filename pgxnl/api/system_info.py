"""시스템 상태 — 사이드바 상태 줄(모든 사용자)과 관리 > 시스템 정보(관리자).

nlxpg 의 상태 표시를 따랐다(2026-10-02 사용자 요청). 전엔 시스템 DB 상태를 볼 곳이
`/healthz`(true/false)와 관리자 설정 응답 속 DSN 뿐이었다.

- `collect_status()`  — 누구에게나: 연결 여부·모델명·대상 DB 연결 수. DSN·경로는 없다.
- `collect_system_info()` — 관리자: 마스킹한 DSN, 풀, PG 버전, 대상별 응답 시간, 단계별 모델,
  임베딩, 서버, 진행 중 평가.

대상 DB 확인은 실제로 접속해 `SELECT 1` 을 해 본다(3초 상한, 동시에). 상태 줄은 화면을 열
때마다 불리므로 30초 동안 결과를 재사용한다.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg

from pgxnl import __version__

PING_TIMEOUT = 3.0
STATUS_TTL = 30.0
_STARTED_AT = time.time()
_status_cache: tuple[float, dict[str, Any]] | None = None


def mask_dsn(dsn: str | None) -> str | None:
    from pgxnl.api.routes_admin import _mask_dsn

    return _mask_dsn(dsn) if dsn else dsn


async def ping_target(name: str, dsn: str, timeout: float = PING_TIMEOUT) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        conn = await asyncpg.connect(dsn, timeout=timeout)
        try:
            await asyncio.wait_for(conn.fetchval("SELECT 1"), timeout)
        finally:
            await conn.close()
        return {"name": name, "ok": True, "ms": round((time.monotonic() - t0) * 1000), "error": None}
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 "연결 안 됨"으로 보여준다
        msg = str(exc) or type(exc).__name__
        return {"name": name, "ok": False, "ms": None, "error": msg[:300]}


async def _ping_all(state) -> list[dict[str, Any]]:
    if state.target_store is None:
        return []
    records = await state.target_store.list_targets()
    results = await asyncio.gather(*(ping_target(r.name, r.dsn) for r in records))
    for r, res in zip(records, results):
        res["dsn"] = mask_dsn(r.dsn)
    return list(results)


async def _default_llm(state) -> dict[str, Any]:
    from pgxnl.settings import settings

    if state.llm_profile_store is not None:
        p = await state.llm_profile_store.get_default_profile()
        if p is not None:
            return {"source": "profile", "name": p.name, "provider": p.provider, "model": p.model}
    return {"source": "env", "name": ".env", "provider": settings.llm_provider, "model": settings.llm_model}


async def collect_status(state, *, use_cache: bool = True) -> dict[str, Any]:
    global _status_cache
    now = time.monotonic()
    if use_cache and _status_cache and now - _status_cache[0] < STATUS_TTL:
        return _status_cache[1]
    targets = await _ping_all(state)
    status = {
        "system_db": state.system_pool is not None,
        "llm": await _default_llm(state),
        "targets": {"ok": sum(t["ok"] for t in targets), "total": len(targets),
                    "down": [t["name"] for t in targets if not t["ok"]]},
    }
    _status_cache = (now, status)
    return status


async def _system_db(state) -> dict[str, Any]:
    from pgxnl.settings import settings

    info: dict[str, Any] = {"dsn": mask_dsn(settings.system_pg_dsn), "ok": state.system_pool is not None,
                            "pool_size_setting": settings.pg_pool_size}
    pool = state.system_pool
    if pool is None:
        return info
    info["pool"] = {"size": pool.get_size(), "idle": pool.get_idle_size(), "max": pool.get_max_size()}
    try:
        row = await pool.fetchrow(
            """
            SELECT current_database() AS db,
                   current_setting('server_version') AS version,
                   pg_size_pretty(pg_database_size(current_database())) AS size,
                   (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector
            """
        )
        info.update(dict(row))
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)[:300]
    return info


async def _stages(state) -> list[dict[str, Any]]:
    from pgxnl.api.llm_profiles import STAGE_LABELS

    store = state.llm_profile_store
    if store is None:
        return []
    config = await store.get_stage_config()
    profiles = {p.id: p for p in await store.list_profiles()}
    default = await store.get_default_profile()
    out = []
    for stage, entry in config.items():
        p = profiles.get(entry["profile_id"]) if entry["profile_id"] else None
        out.append({
            "stage": stage, "label": STAGE_LABELS.get(stage, stage),
            "model": (p or default).model if (p or default) else None,
            "via_default": p is None,
            "disable_thinking": entry["disable_thinking"],
        })
    return out


async def _running_evals(state) -> list[dict[str, Any]]:
    if state.system_pool is None:
        return []
    try:
        rows = await state.system_pool.fetch(
            "SELECT id, run_name, done, total FROM pgxnl_eval_runs WHERE status = 'running' ORDER BY id"
        )
        return [dict(r) for r in rows]
    except Exception:  # noqa: BLE001
        return []


async def vector_coverage(orchestrator, sv) -> list[dict[str, Any]]:
    """스키마별 벡터 색인 현황. state: none(없음 — 모델이 도구로 탐색) / full / partial(위험 —
    틀린 테이블이 컨텍스트에 들어간다. 2026-10-02 card_games 1/6 사례)."""
    indexed = await sv.indexed_tables()
    out = []
    for schema in await orchestrator.list_schemas():
        actual = {t.name for t in await orchestrator.list_tables(schema)}
        have = indexed.get(schema, set())
        n = len(actual & have)
        out.append({
            "schema": schema, "tables": len(actual), "indexed": n,
            "missing": sorted(actual - have), "stale": sorted(have - actual),
            "state": "none" if n == 0 else ("full" if n == len(actual) else "partial"),
        })
    return out


async def _all_vector_coverage(state) -> list[dict[str, Any]]:
    if state.target_store is None:
        return []
    out = []
    for r in await state.target_store.list_targets():
        try:
            orch = await state.get_orchestrator(r.name)
            sv = orch.schema_vector
            if sv is None or not sv.enabled:
                out.append({"target": r.name, "enabled": False, "schemas": []})
                continue
            out.append({"target": r.name, "enabled": True, "schemas": await vector_coverage(orch, sv)})
        except Exception as exc:  # noqa: BLE001 — 대상 하나가 안 열려도 나머지는 보여준다
            out.append({"target": r.name, "enabled": None, "error": str(exc)[:200], "schemas": []})
    return out


async def collect_system_info(state) -> dict[str, Any]:
    from pgxnl.settings import settings

    system_db, targets, stages, llm, evals, vectors = await asyncio.gather(
        _system_db(state), _ping_all(state), _stages(state), _default_llm(state), _running_evals(state),
        _all_vector_coverage(state),
    )
    return {
        "system_db": system_db,
        "targets": targets,
        "llm": {"default": llm, "stages": stages},
        "embedding": {
            "enabled": state.embed_fn is not None, "provider": settings.embedding_provider,
            "model": settings.embedding_model, "dimensions": settings.embedding_dimensions,
            "base_url": settings.embedding_base_url,
            "coverage": vectors,
        },
        "server": {
            "version": __version__, "python": sys.version.split()[0],
            "env_file": str(Path(".env").resolve()),
            "uptime_seconds": round(time.time() - _STARTED_AT),
            "running_evals": evals,
        },
    }
