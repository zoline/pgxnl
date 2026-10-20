"""관리 API. design 문서 §9(REST API 요약) 참고. 전부 admin 권한 필요."""
from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from pgxnl.auth.dependencies import CurrentUser, require_admin
from pgxnl.governance.glossary import SCOPES as GLOSSARY_SCOPES
from pgxnl.governance.glossary_terms import diagnose, normalize_definition, verify_against_catalog

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _mask_dsn(dsn: str) -> str:
    from urllib.parse import urlparse, urlunparse

    try:
        p = urlparse(dsn)
        if p.password:
            host = p.hostname or ""
            if p.port:
                host += f":{p.port}"
            netloc = f"{p.username}:***@{host}"
            return urlunparse(p._replace(netloc=netloc))
    except Exception:  # noqa: BLE001
        pass
    return dsn


def _require(value, message: str):
    if value is None:
        raise HTTPException(503, message)
    return value


def state_pool():
    from pgxnl.api.state import state

    return state.system_pool


# ── 대상 DB 관리 ──────────────────────────────────────
@router.get("/targets")
async def list_targets():
    from pgxnl.api.state import state

    store = _require(state.target_store, "시스템 DB 미연결")
    records = await store.list_targets()
    return {
        "targets": [
            {"name": r.name, "dialect": r.dialect, "dsn": _mask_dsn(r.dsn), "created_at": r.created_at.isoformat()}
            for r in records
        ]
    }


class TargetBody(BaseModel):
    dialect: str = "postgresql"
    dsn: str


@router.put("/targets/{name}")
async def upsert_target(name: str, body: TargetBody):
    from pgxnl.api.state import state

    store = _require(state.target_store, "시스템 DB 미연결")
    record = await store.upsert(name, body.dialect, body.dsn)
    state.invalidate_orchestrator(name)
    if state.schema_cache is not None:
        await state.schema_cache.invalidate(name)
    if state.semantic_cache is not None:
        await state.semantic_cache.invalidate(name)

    # 등록/DSN 변경 직후 스키마 임베딩을 자동으로 채워둔다 — 그래야 다음 질의부터
    # search_tables 도구 호출 없이도 임베딩 기반 스키마 컨텍스트를 바로 쓸 수 있다.
    try:
        orchestrator = await state.get_orchestrator(name)
        sv = orchestrator.schema_vector
        if sv is not None and sv.enabled:
            asyncio.create_task(_rebuild_schema_vector(name, orchestrator, sv))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SchemaVector] %s 등록 후 자동 재구축 시작 실패: %s", name, exc)

    return {"ok": True, "name": record.name, "dialect": record.dialect}


@router.delete("/targets/{name}")
async def delete_target(name: str):
    from pgxnl.api.state import state

    store = _require(state.target_store, "시스템 DB 미연결")
    await store.delete(name)
    state.invalidate_orchestrator(name)
    if state.schema_cache is not None:
        await state.schema_cache.invalidate(name)
    if state.semantic_cache is not None:
        await state.semantic_cache.invalidate(name)
    return {"ok": True}


@router.delete("/targets/{name}/schema-cache")
async def reset_schema_cache(name: str):
    """스키마 캐시 초기화 + 벡터 재구축 트리거 (design 문서 §5.4 재구축 흐름)."""
    from pgxnl.api.state import TargetNotFoundError, state

    cache = _require(state.schema_cache, "SchemaCache 비활성 상태")
    await cache.invalidate(name)

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    sv = orchestrator.schema_vector
    if sv is not None and sv.enabled:
        await sv.invalidate()
        asyncio.create_task(_rebuild_schema_vector(name, orchestrator, sv))

    return {"ok": True, "target": name}


async def _rebuild_schema_vector(name: str, orchestrator, schema_vector) -> None:
    try:
        schemas = await orchestrator.list_schemas()
        total = 0
        for schema in schemas:
            tables = await orchestrator.list_tables(schema)
            described = []
            for t in tables:
                try:
                    described.append(await orchestrator.describe_table(t.schema, t.name))
                except Exception:  # noqa: BLE001
                    continue
            total += await schema_vector.build_all(described)
        logger.info("[SchemaVector] %s 재구축 완료: %d 테이블", name, total)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SchemaVector] %s 재구축 실패: %s", name, exc)


@router.get("/schema-cache/stats")
async def schema_cache_stats():
    from pgxnl.api.state import state

    cache = _require(state.schema_cache, "SchemaCache 비활성 상태")
    store = _require(state.target_store, "시스템 DB 미연결")
    targets = await store.list_targets()
    stats = []
    for t in targets:
        s = await cache.stats(t.name)
        stats.append({"target": t.name, "total": s.total, "by_kind": s.by_kind})
    return {"stats": stats}


@router.get("/targets/{name}/schema-vector")
async def schema_vector_stats(name: str):
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    sv = orchestrator.schema_vector
    if sv is None or not sv.enabled:
        return {"target": name, "count": 0, "enabled": False}
    return {"target": name, "count": await sv.stats(), "enabled": True}


@router.delete("/targets/{name}/schema-vector")
async def reset_schema_vector(name: str):
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    sv = orchestrator.schema_vector
    if sv is None or not sv.enabled:
        raise HTTPException(503, "SchemaVectorIndex 비활성 상태 (EMBEDDING_API_KEY 확인)")
    await sv.invalidate()
    asyncio.create_task(_rebuild_schema_vector(name, orchestrator, sv))
    return {"ok": True, "target": name}


class SchemaVectorTableBody(BaseModel):
    schema_name: str
    table: str


async def _schema_vector_for(name: str):
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    sv = orchestrator.schema_vector
    if sv is None or not sv.enabled:
        raise HTTPException(503, "SchemaVectorIndex 비활성 상태 (EMBEDDING_API_KEY 확인)")
    return orchestrator, sv


async def _describe_schema(orchestrator, schema: str) -> list:
    described = []
    for t in await orchestrator.list_tables(schema):
        try:
            described.append(await orchestrator.describe_table(schema, t.name))
        except Exception:  # noqa: BLE001 — 하나가 안 읽혀도 나머지는 색인한다
            logger.warning("describe_table 실패, 색인에서 제외: %s.%s", schema, t.name, exc_info=True)
    return described


@router.post("/targets/{name}/schema-vector/table")
async def reindex_schema_vector_table(name: str, body: SchemaVectorTableBody):
    """테이블 하나를 재색인한다 — describe_table() 호출마다 자동으로 개별
    재임베딩되던 방식(§5.4)을 없애고, 필요할 때만 명시적으로 요청하는 이 엔드포인트로
    대체했다. 자동 갱신은 사용 패턴에 따라 일부 테이블만 최신값이 되어 세대가 섞이는
    문제가 있었다 — 이 방식은 언제 무엇이 재색인됐는지 호출한 쪽이 명확히 통제한다.

    2026-10-02: 전체 재구축과 **같은 형식**으로 저장한다(조인 관계를 스키마 전체로 계산).
    그리고 같은 스키마에 색인이 빠진 테이블이 있으면 함께 채운다 — card_games 가
    set_translations 하나만 색인된 채 남아, 모든 질문의 스키마 링킹에 그 테이블만
    들어갔다(BIRD qid 340/346). 일부만 있는 인덱스는 없는 것보다 나쁘다."""
    orchestrator, sv = await _schema_vector_for(name)
    tables = await _describe_schema(orchestrator, body.schema_name)
    names = {t.name for t in tables}
    if body.table not in names:
        raise HTTPException(400, f"테이블을 찾을 수 없습니다: {body.schema_name}.{body.table}")
    indexed = (await sv.indexed_tables()).get(body.schema_name, set())
    missing = sorted(names - indexed - {body.table})
    ok = await sv.build_all(tables, only={body.table, *missing})
    if ok == 0:
        raise HTTPException(500, "임베딩 실패 — 서버 로그(스키마 벡터 임베딩 실패)를 확인하세요")
    return {"ok": True, "target": name, "schema": body.schema_name, "table": body.table,
            "filled_missing": missing, "indexed": ok}


@router.get("/targets/{name}/schema-vector/coverage")
async def schema_vector_coverage(name: str):
    """스키마별 색인 현황 — 실제 테이블 수 대비 색인된 수. `partial`(일부만 색인)이 위험하다:
    없으면 모델이 도구로 탐색하지만, 일부만 있으면 틀린 테이블을 컨텍스트에 넣는다."""
    from pgxnl.api.system_info import vector_coverage

    orchestrator, sv = await _schema_vector_for(name)
    return {"target": name, "schemas": await vector_coverage(orchestrator, sv)}


class SchemaVectorFillBody(BaseModel):
    schema_name: str


@router.post("/targets/{name}/schema-vector/fill-missing")
async def schema_vector_fill_missing(name: str, body: SchemaVectorFillBody):
    """한 스키마에서 색인이 빠진 테이블만 채운다(이미 있는 테이블은 건드리지 않는다)."""
    orchestrator, sv = await _schema_vector_for(name)
    tables = await _describe_schema(orchestrator, body.schema_name)
    indexed = (await sv.indexed_tables()).get(body.schema_name, set())
    missing = sorted({t.name for t in tables} - indexed)
    ok = await sv.build_all(tables, only=set(missing)) if missing else 0
    return {"ok": True, "schema": body.schema_name, "filled": missing, "indexed": ok}


# ── 시맨틱 캐시 ────────────────────────────────────────
@router.get("/semantic-cache")
async def semantic_cache_stats():
    from pgxnl.api.state import state

    pool = _require(state.system_pool, "시스템 DB 미연결")
    rows = await pool.fetch(
        """
        SELECT target_db AS target, count(*) AS entries,
               min(created_at) AS oldest, max(created_at) AS newest
        FROM pgxnl_cache GROUP BY target_db ORDER BY target_db
        """
    )
    return {
        "stats": [
            {
                "target": r["target"], "entries": r["entries"],
                "oldest": r["oldest"].isoformat() if r["oldest"] else None,
                "newest": r["newest"].isoformat() if r["newest"] else None,
            }
            for r in rows
        ]
    }


@router.get("/semantic-cache/entries")
async def semantic_cache_entries(
    target: str | None = Query(None), schema_name: str | None = Query(None),
    q: str | None = Query(None), limit: int = 50, offset: int = 0,
):
    """캐시에 실제로 무엇이 들어 있는지. 건수 통계만으로는 손으로 넣은 항목이 맞게
    들어갔는지, 질문 문안이 어떤지 확인할 길이 없다(`SQL 수집` 화면에서 등록하는
    경로가 생기면서 필요해졌다).

    `answer`는 길어서 목록에 싣지 않는다 — 캐시 히트 때 쓰이지도 않는다(매번 새로
    요약한다). 실제로 봐야 하는 것은 질문과 SQL이다.
    """
    from pgxnl.api.state import state

    pool = _require(state.system_pool, "시스템 DB 미연결")
    where, args = ["TRUE"], []
    if target:
        args.append(target)
        where.append(f"target_db = ${len(args)}")
    if schema_name:
        args.append(schema_name)
        where.append(f"schema_name = ${len(args)}")
    if q:
        args.append(f"%{q}%")
        where.append(f"(question ILIKE ${len(args)} OR sql_steps::text ILIKE ${len(args)})")
    clause = " AND ".join(where)

    total = await pool.fetchval(f"SELECT count(*) FROM pgxnl_cache WHERE {clause}", *args)
    rows = await pool.fetch(
        f"""
        SELECT id, target_db, schema_name, question, sql_steps, hit_count, created_at,
               embedding IS NOT NULL AS has_embedding, length(answer) AS answer_len
        FROM pgxnl_cache WHERE {clause}
        ORDER BY created_at DESC LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
        """,
        *args, limit, offset,
    )
    return {
        "total": total,
        "items": [
            {
                "id": r["id"], "target": r["target_db"], "schema_name": r["schema_name"],
                "question": r["question"],
                # jsonb 는 풀 초기화에서 이미 list 로 디코딩된다(main.py `_register_codecs`).
                # 여기서 json.loads 를 또 부르면 터진다.
                "sql": (r["sql_steps"] or [{}])[-1].get("sql"),
                "hit_count": r["hit_count"], "created_at": r["created_at"].isoformat(),
                "has_embedding": r["has_embedding"], "answer_len": r["answer_len"],
            }
            for r in rows
        ],
    }


@router.delete("/semantic-cache/entries/{entry_id}")
async def delete_semantic_cache_entry(entry_id: int):
    """항목 하나만 지운다. 대상 단위 초기화(`DELETE /semantic-cache`)는 손으로 넣은
    것까지 함께 날려서, 잘못 들어간 한 건을 빼는 용도로는 못 쓴다."""
    from pgxnl.api.state import state

    pool = _require(state.system_pool, "시스템 DB 미연결")
    deleted = await pool.fetchval("DELETE FROM pgxnl_cache WHERE id = $1 RETURNING id", entry_id)
    if deleted is None:
        raise HTTPException(404, "없는 항목입니다")
    return {"ok": True, "id": deleted}


@router.delete("/semantic-cache")
async def reset_semantic_cache(target: str | None = Query(None)):
    from pgxnl.api.state import state

    cache = _require(state.semantic_cache, "SemanticCache 비활성 상태")
    if target:
        await cache.invalidate(target)
        return {"ok": True, "target": target}

    store = _require(state.target_store, "시스템 DB 미연결")
    for t in await store.list_targets():
        await cache.invalidate(t.name)
    return {"ok": True, "target": None}


# ── 거버넌스: 규칙 ────────────────────────────────────
class RuleIn(BaseModel):
    target_name: str | None = None
    #: 대상 DB 안의 한 스키마에만 적용(비우면 대상 전체). 등록 후에는 바꿀 수 없다(대상과 같음).
    schema_name: str | None = None
    rule_type: str
    definition: dict
    enabled: bool = True


@router.get("/rules")
async def list_rules():
    from pgxnl.api.state import state

    store = _require(state.rule_store, "시스템 DB 미연결")
    rules = await store.list_all()
    return {
        "rules": [
            {"id": r.id, "target_name": r.target_name, "schema_name": r.schema_name,
             "rule_type": r.rule_type, "definition": r.definition, "enabled": r.enabled}
            for r in rules
        ]
    }


@router.post("/rules")
async def create_rule(rule: RuleIn):
    from pgxnl.api.state import state

    store = _require(state.rule_store, "시스템 DB 미연결")
    if rule.schema_name and not rule.target_name:
        raise HTTPException(400, "스키마 전용 규칙은 대상 DB를 지정해야 합니다")
    rule_id = await store.create(rule.target_name, rule.rule_type, rule.definition, rule.schema_name)
    return {"ok": True, "id": rule_id}


@router.put("/rules/{rule_id}")
async def update_rule(rule_id: int, rule: RuleIn):
    from pgxnl.api.state import state

    store = _require(state.rule_store, "시스템 DB 미연결")
    await store.update(rule_id, definition=rule.definition, enabled=rule.enabled)
    return {"ok": True}


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: int):
    from pgxnl.api.state import state

    store = _require(state.rule_store, "시스템 DB 미연결")
    await store.delete(rule_id)
    return {"ok": True}


# ── 거버넌스: 용어집 ──────────────────────────────────
class GlossaryIn(BaseModel):
    target_name: str | None = None
    schema_name: str | None = None
    term: str
    table_name: str | None = None
    column_name: str | None = None
    definition: str
    is_pii: bool = False
    source: str | None = None
    scope: str = "both"


@router.get("/glossary")
async def list_glossary(
    target_name: str | None = Query(None), schema_name: str | None = Query(None),
    scope: str | None = Query(None),
):
    from pgxnl.api.state import state

    store = _require(state.glossary_store, "시스템 DB 미연결")
    entries = await store.list_all(target_name, schema_name, scope)
    diagnoses = {
        e.id: await _diagnosis_payload(
            e.term, e.column_name, e.definition,
            target_name=e.target_name or target_name,
            schema_name=e.schema_name, table_name=e.table_name,
        )
        for e in entries
    }
    return {
        "entries": [
            {"id": e.id, "term": e.term, "table_name": e.table_name, "column_name": e.column_name,
             "definition": e.definition, "is_pii": e.is_pii, "schema_name": e.schema_name, "source": e.source,
             "scope": e.scope,
             # 필터가 "기본 제외"라 신호 없는 항목은 조용히 한 번도 안 실린다 — 목록에서
             # 바로 보이게 진단을 함께 내려준다(§5.11).
             "diagnosis": diagnoses[e.id]}
            for e in entries
        ]
    }


async def _catalog_warnings(entry_target, schema_name, table_name, column_name) -> list[str]:
    """대상 DB 카탈로그와 대조해 테이블/컬럼이 실재하는지 확인한다.

    `diagnose()`가 순수 함수라 못 잡는 오타(`shcools`)를 여기서 잡는다. 대상 DB에
    못 붙거나 target/schema/table 중 하나라도 NULL이면 조용히 건너뛴다 —
    "판단 불가"는 등록을 막을 사유가 아니다.
    """
    from pgxnl.api.state import state

    if not entry_target or not schema_name or not table_name:
        return []
    try:
        orchestrator = await state.get_orchestrator(entry_target)
        known = {t.name for t in await orchestrator.list_tables(schema_name)}
    except Exception:  # noqa: BLE001
        return []

    async def lookup(schema: str, table: str) -> set[str] | None:
        if table not in known:
            return None
        meta = await orchestrator.describe_table(schema, table)
        return {c.name for c in meta.columns}

    return await verify_against_catalog(
        lookup, target_name=entry_target, schema_name=schema_name,
        table_name=table_name, column_name=column_name, known_tables=known,
    )


async def _diagnosis_payload(
    term: str | None, column_name: str | None, definition: str,
    *, target_name: str | None = None, schema_name: str | None = None,
    table_name: str | None = None,
) -> dict:
    d = diagnose(term, column_name, definition)
    catalog = await _catalog_warnings(target_name, schema_name, table_name, column_name)
    return {
        "aliases": d.aliases, "values": d.values,
        "warnings": d.warnings + catalog,
        # 카탈로그에 없으면 신호가 있어도 실리지 않는다 — is_dead에 반영해야
        # 목록 화면 배지가 정확해진다.
        "is_dead": d.is_dead or bool(catalog),
    }


@router.post("/glossary")
async def create_glossary(entry: GlossaryIn):
    from pgxnl.api.state import state

    if entry.scope not in GLOSSARY_SCOPES:
        raise HTTPException(400, f"scope는 {GLOSSARY_SCOPES} 중 하나여야 합니다")
    store = _require(state.glossary_store, "시스템 DB 미연결")
    definition = normalize_definition(entry.definition)
    entry_id = await store.create(
        entry.target_name, entry.term, definition,
        schema_name=entry.schema_name, table_name=entry.table_name,
        column_name=entry.column_name, is_pii=entry.is_pii, source=entry.source, scope=entry.scope,
    )
    return {
        "ok": True, "id": entry_id, "definition": definition,
        "diagnosis": await _diagnosis_payload(
            entry.term, entry.column_name, definition, target_name=entry.target_name,
            schema_name=entry.schema_name, table_name=entry.table_name,
        ),
    }


@router.put("/glossary/{entry_id}")
async def update_glossary(entry_id: int, entry: GlossaryIn):
    """전체 수정 화면 전용 — scope는 이 엔드포인트로 안 바꾼다(토글은 /scope로 분리돼
    있음, 실수로 같이 덮어써서 목록 화면에서 켜둔 scope가 되돌아가는 걸 방지)."""
    from pgxnl.api.state import state

    store = _require(state.glossary_store, "시스템 DB 미연결")
    definition = normalize_definition(entry.definition)
    await store.update(
        entry_id, entry.term, definition,
        target_name=entry.target_name, schema_name=entry.schema_name, table_name=entry.table_name,
        column_name=entry.column_name, is_pii=entry.is_pii, source=entry.source,
    )
    return {
        "ok": True, "definition": definition,
        "diagnosis": await _diagnosis_payload(
            entry.term, entry.column_name, definition, target_name=entry.target_name,
            schema_name=entry.schema_name, table_name=entry.table_name,
        ),
    }


class GlossaryBulkItem(BaseModel):
    schema_name: str
    table_name: str
    column_name: str
    term: str
    definition: str
    source: str | None = None
    scope: str = "generation"


class GlossaryBulkIn(BaseModel):
    target_name: str
    entries: list[GlossaryBulkItem]
    #: 같은 (스키마, 테이블, 컬럼)에 이미 항목이 있을 때. "skip"이 기본 —
    #: 모르고 덮어쓰면 사람이 쓴 지식이 사라진다.
    on_conflict: str = "skip"   # "skip" | "replace"


@router.post("/glossary/bulk")
async def create_glossary_bulk(body: GlossaryBulkIn):
    """Design Lab 제안을 일괄 등록한다.

    `for_table()`은 컬럼 중복을 막지 않으므로, 같은 컬럼에 두 항목이 등록되면
    **정의가 둘 다 프롬프트에 실린다**(실측: 손수 15건과 자동 20건이 9건 겹쳤다).
    그래서 등록 전에 기존 항목을 확인하고 `on_conflict`에 따라 처리한다 —
    기본은 `skip`이다(사람이 쓴 지식을 모르고 덮어쓰지 않게).
    """
    from pgxnl.api.state import state

    if body.on_conflict not in ("skip", "replace"):
        raise HTTPException(400, "on_conflict는 'skip' 또는 'replace'여야 합니다")
    store = _require(state.glossary_store, "시스템 DB 미연결")

    created, replaced, skipped = [], [], []
    for item in body.entries:
        if item.scope not in GLOSSARY_SCOPES:
            raise HTTPException(400, f"scope는 {GLOSSARY_SCOPES} 중 하나여야 합니다")
        existing = [
            e for e in await store.list_all(body.target_name, item.schema_name)
            if (e.table_name or "") == item.table_name
            and (e.column_name or "").lower() == item.column_name.lower()
        ]
        if existing and body.on_conflict == "skip":
            skipped.append({"table": item.table_name, "column": item.column_name,
                            "existing_id": existing[0].id})
            continue
        for e in existing:
            await store.delete(e.id)
            replaced.append(e.id)
        entry_id = await store.create(
            body.target_name, item.term, normalize_definition(item.definition),
            schema_name=item.schema_name, table_name=item.table_name,
            column_name=item.column_name, source=item.source, scope=item.scope,
        )
        created.append(entry_id)
    return {"ok": True, "created": created, "replaced": replaced, "skipped": skipped}


class GlossaryScopeIn(BaseModel):
    scope: str


@router.put("/glossary/{entry_id}/scope")
async def set_glossary_scope(entry_id: int, body: GlossaryScopeIn):
    from pgxnl.api.state import state

    if body.scope not in GLOSSARY_SCOPES:
        raise HTTPException(400, f"scope는 {GLOSSARY_SCOPES} 중 하나여야 합니다")
    store = _require(state.glossary_store, "시스템 DB 미연결")
    await store.set_scope(entry_id, body.scope)
    return {"ok": True}


@router.delete("/glossary/{entry_id}")
async def delete_glossary(entry_id: int):
    from pgxnl.api.state import state

    store = _require(state.glossary_store, "시스템 DB 미연결")
    await store.delete(entry_id)
    return {"ok": True}


# ── 감사 로그 ─────────────────────────────────────────
@router.get("/audit-log")
async def audit_log(
    target: str | None = None, decision: str | None = None, limit: int = Query(100, le=1000), offset: int = 0,
):
    from pgxnl.api.state import state

    pool = _require(state.system_pool, "시스템 DB 미연결")
    conditions = []
    params: list = []
    if target:
        params.append(target)
        conditions.append(f"target_name = ${len(params)}")
    if decision:
        params.append(decision)
        conditions.append(f"decision = ${len(params)}")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""
        SELECT id, target_name, user_id, question, sql, decision, reason, estimated_cost, created_at
        FROM pgxnl_audit_log {where}
        ORDER BY created_at DESC LIMIT ${len(params) - 1} OFFSET ${len(params)}
        """,
        *params,
    )
    return {
        "items": [
            {
                "id": r["id"], "target_name": r["target_name"], "user_id": r["user_id"],
                "question": r["question"], "sql": r["sql"], "decision": r["decision"],
                "reason": r["reason"], "estimated_cost": r["estimated_cost"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }



def _audit_purge_where(older_than_days: int, target: str | None) -> tuple[str, list]:
    params: list = [older_than_days]
    where = "created_at < now() - make_interval(days => $1)"
    if target:
        params.append(target)
        where += f" AND target_name = ${len(params)}"
    return where, params


@router.get("/audit-log/purge-count")
async def audit_log_purge_count(older_than_days: int = Query(1, ge=0), target: str | None = None):
    """삭제 전 확인용 — `older_than_days` 일 이전 기록이 몇 행인지."""
    from pgxnl.api.state import state

    pool = _require(state.system_pool, "시스템 DB 미연결")
    where, params = _audit_purge_where(older_than_days, target)
    return {"count": await pool.fetchval(f"SELECT count(*) FROM pgxnl_audit_log WHERE {where}", *params)}


@router.delete("/audit-log")
async def audit_log_purge(
    older_than_days: int = Query(1, ge=0), target: str | None = None,
    admin: CurrentUser = Depends(require_admin),
):
    """`older_than_days` 일 이전 감사 로그를 지운다(0 이면 전부). 관리자 전용 — 감사 기록이라 아무나 지우면
    기록의 의미가 없어진다. 누가 언제 무엇을 지웠는지는 서버 로그에 남긴다(2026-10-14)."""
    from pgxnl.api.state import state

    pool = _require(state.system_pool, "시스템 DB 미연결")
    where, params = _audit_purge_where(older_than_days, target)
    status = await pool.execute(f"DELETE FROM pgxnl_audit_log WHERE {where}", *params)
    deleted = int(status.split()[-1])
    logger.warning("감사 로그 삭제: 사용자=%s, %d일 이전, 대상=%s, %d행", admin.username, older_than_days,
                   target or "전체", deleted)
    return {"deleted": deleted}

# ── 설정 / 사용자 ─────────────────────────────────────
# provider별 API 키 환경변수 이름 (PGXNL_ 접두사 없음 — 기존 os.environ 직접 조회 관례).
_API_KEY_ENV_NAMES = {
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "watsonx_api_key": "WATSONX_API_KEY",
    "watsonx_password": "WATSONX_PASSWORD",
}


@router.get("/settings")
async def get_settings():
    import os

    from pgxnl.settings import settings

    return {
        "llm": {
            "provider": settings.llm_provider, "model": settings.llm_model,
            "base_url": settings.llm_base_url, "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "watsonx_project_id": settings.watsonx_project_id,
            "watsonx_space_id": settings.watsonx_space_id,
            "watsonx_username": settings.watsonx_username,
            "watsonx_verify_ssl": settings.watsonx_verify_ssl,
            "watsonx_instance_id": settings.watsonx_instance_id,
            # 키/비밀번호 값 자체는 절대 반환하지 않는다 — 설정 여부만 알려준다.
            "api_keys_set": {
                field: bool(os.environ.get(env_name)) for field, env_name in _API_KEY_ENV_NAMES.items()
            },
        },
        "agent": {
            "max_iterations": settings.agent_max_iterations, "max_corrections": settings.agent_max_corrections,
            "sample_rows": settings.agent_sample_rows, "stats_top_n": settings.agent_stats_top_n,
            "max_context_tables": settings.agent_max_context_tables,
        },
        "cache": {
            "enabled": settings.cache_enabled, "similarity_threshold": settings.cache_similarity_threshold,
            "ttl_seconds": settings.cache_ttl_seconds,
        },
        "system_pg": {"dsn": _mask_dsn(settings.system_pg_dsn), "pool_size": settings.pg_pool_size},
    }


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    watsonx_project_id: str | None = None
    watsonx_space_id: str | None = None
    watsonx_username: str | None = None
    watsonx_verify_ssl: bool | None = None
    watsonx_instance_id: str | None = None
    agent_max_iterations: int | None = None
    agent_max_corrections: int | None = None
    cache_enabled: bool | None = None
    cache_similarity_threshold: float | None = None
    # 비어있으면 무시(기존 값 유지) — 입력한 경우에만 교체. 조회 응답에는 절대 포함되지 않는다.
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    watsonx_api_key: str | None = None
    watsonx_password: str | None = None


_LLM_SETTING_KEYS = {
    "llm_provider", "llm_model", "llm_base_url", "llm_temperature", "llm_max_tokens",
    "watsonx_project_id", "watsonx_space_id", "watsonx_username", "watsonx_verify_ssl", "watsonx_instance_id",
}


@router.put("/settings")
async def update_settings(body: SettingsUpdate):
    import os

    from pgxnl.api.state import create_llm_client, state
    from pgxnl.settings import persist_env_updates, persist_raw_env_updates, settings

    all_updates = body.model_dump(exclude_none=True)
    key_updates = {k: v for k, v in all_updates.items() if k in _API_KEY_ENV_NAMES and v}
    field_updates = {k: v for k, v in all_updates.items() if k not in _API_KEY_ENV_NAMES}

    for key, value in field_updates.items():
        setattr(settings, key, value)
    if field_updates:
        persist_env_updates(field_updates)  # .env에도 반영 — 재기동해도 유지됨

    if key_updates:
        raw_env = {_API_KEY_ENV_NAMES[k]: v for k, v in key_updates.items()}
        os.environ.update(raw_env)  # 재기동 없이 현재 프로세스에도 즉시 반영
        persist_raw_env_updates(raw_env)

    if _LLM_SETTING_KEYS & field_updates.keys() or key_updates:
        state.llm = create_llm_client(settings)  # provider/model/자격 변경은 클라이언트 재생성이 필요

    state.orchestrators.clear()  # 다음 요청부터 새 설정 반영
    state.user_orchestrators.clear()
    updated = [*field_updates.keys(), *key_updates.keys()]
    return {"ok": True, "updated": updated}


# ── 모델 설정 (단계별 LLM 등록부) ──────────────────────
def _require_llm_profile_store():
    from pgxnl.api.state import state

    return _require(state.llm_profile_store, "시스템 DB 미연결")


def _profile_to_dict(p) -> dict:
    return {
        "id": p.id, "name": p.name, "provider": p.provider, "model": p.model, "base_url": p.base_url,
        "temperature": p.temperature, "max_tokens": p.max_tokens, "has_api_key": p.has_api_key,
        "watsonx_project_id": p.watsonx_project_id, "watsonx_space_id": p.watsonx_space_id,
        "watsonx_username": p.watsonx_username, "has_watsonx_password": p.has_watsonx_password,
        "watsonx_instance_id": p.watsonx_instance_id, "watsonx_api_version": p.watsonx_api_version,
        "watsonx_verify_ssl": p.watsonx_verify_ssl, "is_default": p.is_default,
        "created_at": p.created_at.isoformat(),
    }


@router.get("/models")
async def list_models():
    store = _require_llm_profile_store()
    return {"models": [_profile_to_dict(p) for p in await store.list_profiles()]}


class ModelBody(BaseModel):
    provider: str
    model: str
    name: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    max_tokens: int = 4096
    api_key: str | None = None
    watsonx_project_id: str | None = None
    watsonx_space_id: str | None = None
    watsonx_username: str | None = None
    watsonx_password: str | None = None
    watsonx_instance_id: str | None = None
    watsonx_api_version: str | None = None
    watsonx_verify_ssl: bool = True


@router.post("/models")
async def create_model(body: ModelBody):
    from pgxnl.api.state import state

    store = _require_llm_profile_store()
    try:
        profile = await store.create_profile(
            body.provider, body.model, name=body.name, base_url=body.base_url,
            temperature=body.temperature, max_tokens=body.max_tokens, api_key=body.api_key,
            watsonx_project_id=body.watsonx_project_id, watsonx_space_id=body.watsonx_space_id,
            watsonx_username=body.watsonx_username, watsonx_password=body.watsonx_password,
            watsonx_instance_id=body.watsonx_instance_id, watsonx_api_version=body.watsonx_api_version,
            watsonx_verify_ssl=body.watsonx_verify_ssl,
        )
    except Exception as exc:
        raise HTTPException(400, f"모델 등록 실패 (이미 등록된 provider+model 조합일 수 있습니다): {exc}") from exc
    state.invalidate_llm_stage_config()
    return _profile_to_dict(profile)


class ModelUpdateBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    name: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    api_key: str | None = None
    watsonx_project_id: str | None = None
    watsonx_space_id: str | None = None
    watsonx_username: str | None = None
    watsonx_password: str | None = None
    watsonx_instance_id: str | None = None
    watsonx_api_version: str | None = None
    watsonx_verify_ssl: bool | None = None


@router.put("/models/{model_id}")
async def update_model(model_id: int, body: ModelUpdateBody):
    from pgxnl.api.state import state

    store = _require_llm_profile_store()
    updates = body.model_dump(exclude_none=True)
    profile = await store.update_profile(model_id, **updates)
    if profile is None:
        raise HTTPException(404, "모델을 찾을 수 없습니다")
    state.invalidate_llm_stage_config()
    return _profile_to_dict(profile)


@router.delete("/models/{model_id}")
async def delete_model(model_id: int):
    from pgxnl.api.state import state

    store = _require_llm_profile_store()
    deleted = await store.delete_profile(model_id)
    state.invalidate_llm_stage_config()
    return {"ok": True, "deleted": deleted}


@router.post("/models/{model_id}/set-default")
async def set_default_model(model_id: int):
    """등록된 모델 중 하나를 "기본 모델"로 지정한다 — 관리자 단계별 지정에서 특정
    단계를 고르지 않았을 때 최종적으로 쓰이는 모델(그마저 없으면 .env 기반 설정)."""
    from pgxnl.api.state import state

    store = _require_llm_profile_store()
    try:
        await store.set_default_profile(model_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    state.invalidate_llm_stage_config()
    return {"ok": True}


async def _test_llm_client(client) -> dict:
    """짧은 요청을 보내 접속/인증/모델명이 유효한지 확인한다. 실패해도 500이 아니라
    ok:false로 응답하고, 진단에 필요한 원본 오류 메시지를 그대로 돌려준다
    (watsonx CPD 연동 디버깅 때처럼 오류 본문을 숨기지 않는 게 중요했다)."""
    import time

    t0 = time.monotonic()
    try:
        resp = await client.complete(
            system_prompt="다음 지시를 정확히 따르세요.",
            messages=[{"role": "user", "content": "정확히 이 단어만 출력하세요: OK"}],
        )
        elapsed_ms = (time.monotonic() - t0) * 1000
        return {"ok": True, "response_text": (resp.text or "").strip()[:200], "elapsed_ms": elapsed_ms}
    except Exception as exc:  # noqa: BLE001 — 테스트 목적상 오류를 그대로 사용자에게 보여줘야 함
        elapsed_ms = (time.monotonic() - t0) * 1000
        return {"ok": False, "error": str(exc), "elapsed_ms": elapsed_ms}


@router.post("/models/test")
async def test_model_draft(body: ModelBody):
    """등록 폼에 입력한 값을 저장하지 않고 바로 테스트한다 — "등록" 누르기 전에 접속을
    미리 확인할 때 쓴다."""
    from pgxnl.api.state import create_llm_client_from_profile

    payload = body.model_dump()
    payload["api_key"] = payload.get("api_key") or ""
    client = create_llm_client_from_profile(payload)
    return await _test_llm_client(client)


@router.post("/models/{model_id}/test")
async def test_model(model_id: int):
    """이미 등록된 모델에 실제로 짧은 요청을 보내 접속/인증/모델명이 유효한지 확인한다."""
    from pgxnl.api.state import create_llm_client_from_profile

    store = _require_llm_profile_store()
    secrets = await store.get_profile_secrets(model_id)
    if secrets is None:
        raise HTTPException(404, "모델을 찾을 수 없습니다")
    client = create_llm_client_from_profile(secrets)
    return await _test_llm_client(client)


@router.get("/model-stage-config")
async def get_model_stage_config():
    from pgxnl.api.llm_profiles import STAGE_LABELS
    from pgxnl.settings import settings

    store = _require_llm_profile_store()
    config = await store.get_stage_config()
    profiles = {p.id: p for p in await store.list_profiles()}
    default_profile = await store.get_default_profile()
    default_label = (
        f"{default_profile.provider}/{default_profile.model} ({default_profile.name})" if default_profile
        else f"{settings.llm_provider}/{settings.llm_model} (.env 설정, 등록된 기본 모델 없음)"
    )
    return {
        "stages": [
            {
                "stage": stage, "label": STAGE_LABELS[stage], "profile_id": entry["profile_id"],
                "disable_thinking": entry["disable_thinking"],
                "model": _profile_to_dict(profiles[entry["profile_id"]]) if entry["profile_id"] in profiles else None,
            }
            for stage, entry in config.items()
        ],
        "default_model": default_label,
    }


class StageAssignBody(BaseModel):
    stage: str
    profile_id: int | None = None
    disable_thinking: bool = False


@router.put("/model-stage-config")
async def set_model_stage_config(body: StageAssignBody):
    from pgxnl.api.state import state

    store = _require_llm_profile_store()
    try:
        await store.set_stage_profile(body.stage, body.profile_id, body.disable_thinking)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    state.invalidate_llm_stage_config()
    return {"ok": True}


@router.get("/users")
async def list_users():
    from pgxnl.api.state import state

    store = _require(state.user_store, "시스템 DB 미연결")
    users = await store.list_users()
    return {
        "users": [
            {"id": u.id, "username": u.username, "email": u.email, "role": u.role, "created_at": u.created_at.isoformat()}
            for u in users
        ]
    }


class CreateUserBody(BaseModel):
    username: str
    email: str | None = None
    role: str = "user"
    password: str | None = None


@router.post("/users")
async def create_user(body: CreateUserBody):
    from pgxnl.api.state import state

    store = _require(state.user_store, "시스템 DB 미연결")
    record, api_key, password = await store.create_user(
        body.username, role=body.role, email=body.email, password=body.password,
    )
    return {
        "user": {"id": record.id, "username": record.username, "role": record.role, "email": record.email},
        "api_key": api_key,
        "password": password,
    }


# ── 사용자별 DB 자격증명 (admin 대리 관리) ───────────────
class CredentialBody(BaseModel):
    db_username: str
    db_password: str


@router.get("/credentials/{user_id}")
async def admin_list_credentials(user_id: int):
    from pgxnl.api.state import state

    store = _require(state.user_store, "시스템 DB 미연결")
    creds = await store.list_credentials(user_id)
    return {
        "credentials": [
            {"target_name": c.target_name, "db_username": c.db_username, "updated_at": c.updated_at.isoformat()}
            for c in creds
        ]
    }


@router.put("/credentials/{user_id}/{target}")
async def admin_set_credential(user_id: int, target: str, body: CredentialBody):
    from pgxnl.api.state import state

    store = _require(state.user_store, "시스템 DB 미연결")
    await store.set_credential(user_id, target, body.db_username, body.db_password)
    state.invalidate_user_orchestrator(user_id, target)
    return {"ok": True, "target": target}


@router.delete("/credentials/{user_id}/{target}")
async def admin_delete_credential(user_id: int, target: str):
    from pgxnl.api.state import state

    store = _require(state.user_store, "시스템 DB 미연결")
    await store.delete_credential(user_id, target)
    state.invalidate_user_orchestrator(user_id, target)
    return {"ok": True}


# ── JOIN 그래프 ────────────────────────────────────────
@router.get("/targets/{name}/join-graph")
async def join_graph_edges(name: str, schema: str = ""):
    """`schema`를 주면 그 스키마 관계 + 스키마 미상('') 관계만."""
    from pgxnl.agent.discovery.graph import list_edges

    pool = _require(state_pool(), "시스템 DB 미연결")
    edges = await list_edges(pool, name, schema=schema or None)
    return {
        "edges": [
            {"id": e.id, "schema_name": e.schema_name,
             "table_a": e.table_a, "column_a": e.column_a, "table_b": e.table_b, "column_b": e.column_b,
             "source": e.source, "confidence": e.confidence, "calls": e.calls, "reviewed": e.reviewed}
            for e in edges
        ]
    }


class JoinReviewBody(BaseModel):
    ids: list[int]


@router.post("/targets/{name}/join-graph/approve")
async def join_graph_approve(name: str, body: JoinReviewBody):
    """수집된 JOIN 후보를 승인해 그래프/경로탐색에 반영한다 — 승인 전에는 pgxnl_join_candidates에
    쌓이기만 하고 find_path()에서 쓰이지 않는다."""
    from pgxnl.agent.discovery.graph import approve_edges

    pool = _require(state_pool(), "시스템 DB 미연결")
    n = await approve_edges(pool, name, body.ids)
    return {"ok": True, "approved": n}


@router.post("/targets/{name}/join-graph/unapprove")
async def join_graph_unapprove(name: str, body: JoinReviewBody):
    """승인을 해제해 대기 후보로 되돌린다(삭제 아님). 질의에는 해당 스키마를 재색인해야 반영된다 —
    승인된 조인은 색인 시점에 스키마 정보([Direct Joins])로 굳기 때문이다."""
    from pgxnl.agent.discovery.graph import unapprove_edges

    pool = _require(state_pool(), "시스템 DB 미연결")
    n = await unapprove_edges(pool, name, body.ids)
    return {"ok": True, "unapproved": n}


@router.get("/targets/{name}/join-graph/{edge_id}/statements")
async def join_graph_edge_statements(name: str, edge_id: int):
    """이 JOIN 엣지가 실제로 어떤 SQL에서 나왔는지. `pgxnl_join_candidates`는
    집계값(누적 calls)만 갖고 있어 클릭해도 "왜 이 관계가 있다고 판단했는지"를
    보여줄 방법이 없었다 — 후보든 승인된 것이든 마찬가지였다. 저장된 값을 조회
    하는 대신 SQL 수집·승인된 사용례를 매번 다시 훑어 파서로 확인한다(자세한
    이유는 graph.py의 find_statements_for_edge 참고) — 기존 데이터에도 코드
    변경 없이 바로 적용된다."""
    from pgxnl.agent.discovery.graph import find_statements_for_edge
    from pgxnl.api.state import state

    pool = _require(state_pool(), "시스템 DB 미연결")
    edge = await pool.fetchrow(
        "SELECT table_a, column_a, table_b, column_b FROM pgxnl_join_candidates WHERE id = $1 AND target_name = $2",
        edge_id, name,
    )
    if edge is None:
        raise HTTPException(404, "없는 JOIN 관계입니다")
    if state.parser is None:
        raise HTTPException(503, "SQL 파서가 초기화되지 않았습니다")
    items = await find_statements_for_edge(
        pool, state.parser, name, edge["table_a"], edge["column_a"], edge["table_b"], edge["column_b"],
    )
    return {
        "edge": dict(edge),
        "items": [
            {"sql": i.sql_text, "call_count": i.call_count, "source": i.source,
             "confirmed": i.confirmed, "question": i.question}
            for i in items
        ],
    }


@router.post("/targets/{name}/join-graph/reject")
async def join_graph_reject(name: str, body: JoinReviewBody):
    from pgxnl.agent.discovery.graph import reject_edges

    pool = _require(state_pool(), "시스템 DB 미연결")
    n = await reject_edges(pool, name, body.ids)
    return {"ok": True, "rejected": n}


class ManualJoinEdgeBody(BaseModel):
    #: 두 테이블이 속한 스키마(2026-10-07). 비우면 테이블 이름의 `schema.` 접두에서 떼고,
    #: 그것도 없으면 대상 DB 카탈로그에서 찾는다.
    schema_name: str = ""
    table_a: str
    column_a: str
    table_b: str
    column_b: str
    #: 기본은 관리 화면에서 직접 등록하는 경우('manual'). Design Lab의 "단계별
    #: 3NF 적용" 마법사는 'design_proposal'을 보낸다 — 그 관계가 가리키는
    #: 룩업 테이블이 아직 실제로 없어서(시뮬레이션만 함) 실제 관계와 구분해야
    #: 한다. graph.py의 add_manual_edge 설명 참고.
    source: str = "manual"


@router.post("/targets/{name}/join-graph/manual")
async def join_graph_add_manual(name: str, body: ManualJoinEdgeBody):
    """직접(또는 도구가 대신) JOIN 관계를 등록한다 — 실행이력/SQL 수집으로
    발견되지 않은 관계를 사람이 직접 아는 경우를 위한 경로. 등록 즉시 승인
    상태로 들어간다."""
    from pgxnl.agent.discovery.graph import add_manual_edge

    for field_name in ("table_a", "column_a", "table_b", "column_b"):
        if not getattr(body, field_name).strip():
            raise HTTPException(400, f"{field_name}은(는) 비어 있을 수 없습니다")

    pool = _require(state_pool(), "시스템 DB 미연결")
    schema = body.schema_name.strip()
    if not schema and "." not in body.table_a and "." not in body.table_b:
        schema = await _schema_of_tables(name, [body.table_a, body.table_b])
    edge = await add_manual_edge(
        pool, name, body.table_a, body.column_a, body.table_b, body.column_b,
        source=body.source, schema_name=schema,
    )
    return {"ok": True, "id": edge.id, "schema_name": edge.schema_name}


async def _target_schema_map(name: str) -> dict[str, str | None]:
    """대상 DB 카탈로그: 맨 테이블 이름(소문자) -> 스키마. 여러 스키마에 있으면 None."""
    from pgxnl.api.state import state

    orchestrator = await state.get_orchestrator(name)
    out: dict[str, str | None] = {}
    for schema in await orchestrator.list_schemas():
        for t in await orchestrator.list_tables(schema):
            key = t.name.lower()
            out[key] = None if key in out and out[key] != schema.lower() else schema.lower()
    return out


async def _schema_of_tables(name: str, tables: list[str]) -> str:
    """테이블들 중 카탈로그에 있는 것의 스키마. 하나로 정해지지 않으면 '' (미상).
    Design Lab 제안처럼 한쪽 테이블이 아직 없어도 다른 쪽으로 정해진다."""
    try:
        schema_of = await _target_schema_map(name)
    except Exception:  # noqa: BLE001 — 카탈로그를 못 읽어도 등록은 막지 않는다(미상으로 저장)
        return ""
    found = {schema_of.get(t.strip().strip('"').lower()) for t in tables} - {None}
    return found.pop() if len(found) == 1 else ""


@router.post("/targets/{name}/join-graph/backfill-schema")
async def join_graph_backfill_schema(name: str):
    """스키마 미상('') 관계를 대상 DB 카탈로그로 채운다(2026-10-07 schema_name 열 도입 시 이전용)."""
    from pgxnl.agent.discovery.graph import backfill_schema_names

    pool = _require(state_pool(), "시스템 DB 미연결")
    return {"ok": True, **await backfill_schema_names(pool, name, await _target_schema_map(name))}


@router.get("/targets/{name}/join-path")
async def join_graph_path(name: str, from_table: str, to_table: str, max_hops: int = 5, schema: str = ""):
    from pgxnl.agent.discovery.graph import find_path

    pool = _require(state_pool(), "시스템 DB 미연결")
    path = await find_path(pool, name, from_table, to_table, max_hops, schema=schema or None)
    if path is None:
        return {"found": False, "path": None}
    return {
        "found": True,
        "path": {
            "tables": path.tables,
            "hops": path.hops,
            "edges": [
                {"table_a": e.table_a, "column_a": e.column_a, "table_b": e.table_b, "column_b": e.column_b}
                for e in path.edges
            ],
        },
    }


@router.delete("/targets/{name}/join-graph")
async def join_graph_delete(name: str):
    from pgxnl.agent.discovery.graph import delete_target

    pool = _require(state_pool(), "시스템 DB 미연결")
    deleted = await delete_target(pool, name)
    return {"ok": True, "deleted": deleted}


class DiscoverJoinsBody(BaseModel):
    limit: int = 500


@router.post("/targets/{name}/discover-joins")
async def discover_joins(name: str, body: DiscoverJoinsBody = DiscoverJoinsBody()):
    """대상 DB의 pg_stat_statements에서 JOIN 조건을 역추적해 pgxnl_join_candidates에 적재한다."""
    from pgxnl.agent.discovery.join_history import discover_joins_from_history, persist_candidates
    from pgxnl.api.state import TargetNotFoundError, state

    pool = _require(state.system_pool, "시스템 DB 미연결")
    try:
        orchestrator = await state.get_orchestrator(name)
        await orchestrator._ensure_initialized()
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    try:
        candidates = await discover_joins_from_history(orchestrator._conn.pool, state.parser, limit=body.limit)
    except Exception as exc:
        raise HTTPException(400, f"실행이력 조회 실패: {exc}") from exc

    await persist_candidates(pool, name, candidates)
    return {"ok": True, "discovered": len(candidates)}


# ── SQL 수집 ───────────────────────────────────────────
class CollectStatementsBody(BaseModel):
    min_calls: int = 1
    limit: int = 1000


@router.post("/targets/{name}/collect-statements")
async def collect_statements(name: str, body: CollectStatementsBody = CollectStatementsBody()):
    from pgxnl.agent.discovery.statements import collect_from_pg_stat_statements
    from pgxnl.api.state import TargetNotFoundError, state

    store = _require(state.statement_store, "시스템 DB 미연결")
    pool = _require(state.system_pool, "시스템 DB 미연결")
    try:
        orchestrator = await state.get_orchestrator(name)
        await orchestrator._ensure_initialized()
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    summary = await collect_from_pg_stat_statements(
        orchestrator._conn, name, state.parser, store, pool,
        min_calls=body.min_calls, limit=body.limit,
    )
    return summary.as_dict()


@router.post("/targets/{name}/collect-statements/upload")
async def collect_statements_upload(name: str, file: UploadFile):
    from pgxnl.agent.discovery.statements import collect_from_file
    from pgxnl.api.state import state

    store = _require(state.statement_store, "시스템 DB 미연결")
    pool = _require(state.system_pool, "시스템 DB 미연결")
    content = await file.read()
    summary = await collect_from_file(content, file.filename or "upload.json", name, state.parser, store, pool)
    return summary.as_dict()


@router.get("/targets/{name}/statements")
async def list_statements(name: str, sql_type: str | None = None, limit: int = 100, offset: int = 0):
    from pgxnl.api.state import state

    store = _require(state.statement_store, "시스템 DB 미연결")
    stmts = await store.list_by_target(name, sql_type=sql_type, limit=limit, offset=offset)
    total = await store.count(name)
    return {
        "total": total,
        "items": [
            {"id": s.id, "sql_hash": s.sql_hash, "sql_type": s.sql_type, "call_count": s.call_count,
             "mean_time_ms": s.mean_time_ms, "tables_used": s.tables_used,
             "sql_text": s.sql_text, "source": s.source}
            for s in stmts
        ],
    }


_PARAM_PLACEHOLDER = re.compile(r"\$(\d+)")


def _substitute_params(sql: str, params: list[str]) -> str:
    """pg_stat_statements가 정규화한 $1,$2,... 자리표시자를 사용자가 입력한 원시 SQL
    리터럴/식으로 그대로 치환한다 (예: "5", "'active'", "now() - interval '1 day'").

    admin 전용 신뢰 경로 — 이미 EXPLAIN ANALYZE로 임의 SQL을 직접 실행할 수 있는
    권한과 동급이므로, 여기서 추가로 막을 권한 경계는 없다. 실제 실행은
    execute_readonly가 READ ONLY 트랜잭션 안에서 하므로 DML/DDL은 DB가 거부한다.
    """
    def repl(m: re.Match) -> str:
        idx = int(m.group(1)) - 1
        return params[idx] if 0 <= idx < len(params) else m.group(0)

    return _PARAM_PLACEHOLDER.sub(repl, sql)


class StatementRunBody(BaseModel):
    sql: str
    params: list[str] = []
    schema_name: str = "public"
    row_limit: int = 100


@router.post("/targets/{name}/statements/run")
async def run_statement(name: str, body: StatementRunBody):
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    sql = _substitute_params(body.sql, body.params)
    try:
        rows = await orchestrator.execute_readonly(
            sql, row_limit=body.row_limit, timeout_seconds=30, schema=body.schema_name,
        )
    except Exception as exc:
        raise HTTPException(400, f"실행 오류: {exc}") from exc
    return {"rows": rows, "row_count": len(rows), "sql": sql}


class StatementDescribeBody(BaseModel):
    sql: str
    params: list[str] = []


@router.post("/targets/{name}/statements/describe")
async def describe_statement(name: str, body: StatementDescribeBody):
    """수집된 SQL -> 자연어 질문. 저장하지 않는다 — 화면에서 사람이 고친 뒤 /cache 로 넣는다."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    sql = _substitute_params(body.sql, body.params)
    try:
        question = await orchestrator.describe_sql_question(sql)
    except TimeoutError as exc:
        raise HTTPException(504, "질문 생성 시간 초과 — 모델 설정의 'SQL -> 자연어 질문' 단계를 확인하세요") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"질문 생성 실패: {exc}") from exc
    if not question:
        raise HTTPException(502, "모델이 빈 응답을 돌려줬습니다")
    return {"question": question, "sql": sql}


class StatementCacheBody(BaseModel):
    question: str
    sql: str
    params: list[str] = []
    schema_name: str = "public"


@router.post("/targets/{name}/statements/cache")
async def cache_statement(name: str, body: StatementCacheBody):
    """질문 + 수집된 SQL을 시맨틱 캐시에 넣는다. SQL은 그대로 들어간다(Canonicalization만 거친다)."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    sql = _substitute_params(body.sql, body.params)
    try:
        return await orchestrator.cache_verified_sql(body.question, sql, schema=body.schema_name)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — 대부분 SQL 실행 오류다(스키마가 바뀌었거나 $N 미치환)
        raise HTTPException(400, f"SQL 실행 실패 — 캐시에 넣지 않았습니다: {exc}") from exc


# ── 승인된 사용례 (기존/유사 Query 탐색) ──────────────────────────────────
# 등록·수정·승인·삭제는 admin 전용으로 남긴다 — 승인 절차의 본체(설명이 실제로
# 맞는지 확인)가 여기 있다. **조회만** 일반 사용자에게 열었다(routes_analyze.py의
# GET /api/targets/{name}/verified-queries, 2026-09-15) — "SQL 미숙련 사용자용
# 자연어 Query 툴"이 제품 목적이라면([[pgxnl_purpose_reframe]] 참고) 그 목적에
# 맞는 도구를 admin 뒤에 잠가둘 이유가 없다.

async def _pii_tables(target: str, schema: str, tables: list[str]) -> bool:
    """참조 테이블 중 PII 컬럼이 등록된 것이 있는지. 승인자가 보고 거르라고 두는
    표시이지 차단이 아니다."""
    from pgxnl.api.state import state

    gs = state.glossary_store
    if gs is None:
        return False
    for t in tables:
        short = t.rsplit(".", 1)[-1]
        try:
            if await gs.pii_columns(target, schema, short):
                return True
        except Exception:  # noqa: BLE001 — 표시용이므로 실패가 등록을 막으면 안 된다
            logger.warning("PII 판정 실패: %s.%s", schema, short, exc_info=True)
    return False


class VerifiedAddBody(BaseModel):
    question: str
    sql: str
    schema_name: str = "public"
    tables_used: list[str] = []


@router.post("/targets/{name}/verified-queries")
async def add_verified_query(
    name: str, body: VerifiedAddBody, user: CurrentUser = Depends(require_admin),
):
    """사용례로 등록한다. 승인은 따로 한다 — 등록만으로는 탐색에 안 나온다."""
    from pgxnl.api.state import state

    store = _require(state.verified_store, "시스템 DB 미연결")
    question = body.question.strip()
    if not question or not body.sql.strip():
        raise HTTPException(400, "질문과 SQL이 모두 있어야 합니다")

    # 참조 테이블은 서버에서 뽑는다. 수집 경로는 목록에 이미 들고 있지만, 사람이
    # 직접 쓴 SQL(Query 화면)은 그게 없다 — 호출자에게 맡기면 그쪽만 테이블 필터가
    # 안 먹는다. 파싱 실패는 등록을 막지 않는다(필터가 덜 듣는 것뿐이다).
    tables = list(body.tables_used)
    if not tables and state.parser is not None:
        try:
            parsed = state.parser.parse(body.sql)
            if parsed.is_well_formed:
                tables = parsed.referenced_tables
        except Exception:  # noqa: BLE001
            logger.warning("사용례 테이블 추출 실패", exc_info=True)

    embedding = None
    if state.embed_fn is not None:
        try:
            embedding = await state.embed_fn(question)
        except Exception:  # noqa: BLE001 — 임베딩은 순위 재료일 뿐이다. 없으면 trgm으로 내려앉는다
            logger.warning("사용례 임베딩 실패, 어휘 유사도로 진행합니다", exc_info=True)

    entry_id = await store.add(
        name, question, body.sql, schema_name=body.schema_name,
        tables_used=tables,
        has_pii=await _pii_tables(name, body.schema_name, tables),
        created_by=user.id, embedding=embedding,
    )
    if entry_id is None:
        return {"added": False, "reason": "같은 SQL이 이미 등록돼 있습니다"}
    return {"added": True, "id": entry_id}


class VerifiedUpdateBody(BaseModel):
    question: str | None = None
    sql: str | None = None


@router.patch("/verified-queries/{entry_id}")
async def update_verified_query(entry_id: int, body: VerifiedUpdateBody):
    from pgxnl.api.state import state

    store = _require(state.verified_store, "시스템 DB 미연결")
    if not await store.update(entry_id, question=body.question, sql_text=body.sql):
        raise HTTPException(404, "없는 항목이거나 바꿀 내용이 없습니다")
    return {"ok": True}


@router.post("/verified-queries/{entry_id}/approve")
async def approve_verified_query(
    entry_id: int, approved: bool = True, user: CurrentUser = Depends(require_admin),
):
    from pgxnl.api.state import state

    store = _require(state.verified_store, "시스템 DB 미연결")
    if not await store.set_approved(entry_id, approved, user_id=user.id):
        raise HTTPException(404, "없는 항목입니다")
    return {"ok": True, "approved": approved}


@router.delete("/verified-queries/{entry_id}")
async def delete_verified_query(entry_id: int):
    from pgxnl.api.state import state

    store = _require(state.verified_store, "시스템 DB 미연결")
    if not await store.delete(entry_id):
        raise HTTPException(404, "없는 항목입니다")
    return {"ok": True}


@router.delete("/targets/{name}/statements")
async def delete_statements(name: str):
    from pgxnl.api.state import state

    store = _require(state.statement_store, "시스템 DB 미연결")
    deleted = await store.delete_target(name)
    return {"ok": True, "deleted": deleted}


# ── BIRD 벤치마크 평가 ─────────────────────────────────
def _require_eval_store():
    from pgxnl.api.state import state

    return _require(state.eval_store, "시스템 DB 미연결")


@router.get("/targets/{name}/schemas")
async def list_target_schemas(name: str):
    """평가 대상 DB가 가진 스키마 목록. BIRD 평가에서 db_id별 필터링에 사용."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"schemas": await orchestrator.list_schemas()}


@router.post("/targets/{name}/eval/runs")
async def start_eval(
    name: str, run_name: str = "", concurrency: int = 1, schema: str = "",
    file: UploadFile | None = File(None), admin: CurrentUser = Depends(require_admin),
):
    from pgxnl.agent.evaluation.bird import (
        DEFAULT_BIRD_DATASET_PATH, align_seq_to_default, parse_bird_json, run_evaluation,
    )
    from pgxnl.api.state import TargetNotFoundError, state

    eval_store = _require_eval_store()
    if file is not None and file.filename:
        raw = await file.read()
        source_label = file.filename
    else:
        # 파일을 선택하지 않으면 번들된 기본 BIRD MiniDev 데이터셋으로 실행 —
        # 스키마 선택만으로 바로 평가를 돌릴 수 있게 한다.
        if not DEFAULT_BIRD_DATASET_PATH.exists():
            raise HTTPException(400, "파일을 선택하지 않았고 기본 BIRD 데이터셋도 찾을 수 없습니다")
        raw = DEFAULT_BIRD_DATASET_PATH.read_bytes()
        source_label = DEFAULT_BIRD_DATASET_PATH.name

    try:
        data = json.loads(raw)
    except Exception as exc:
        raise HTTPException(400, f"JSON 파싱 오류: {exc}") from exc
    if not isinstance(data, list):
        raise HTTPException(400, "JSON 배열이어야 합니다")

    items = parse_bird_json(data)
    if not items:
        raise HTTPException(400, "평가 항목이 없습니다 (SQL/gold_sql 필드 확인)")
    if file is not None and file.filename:
        items = align_seq_to_default(items)

    # schema가 지정되면 해당 db_id 문항만 실행 — "전체"(빈 문자열)면 파일 내 전체 문항 실행.
    if schema:
        items = [it for it in items if (it.get("db_id") or "public") == schema]
        if not items:
            raise HTTPException(400, f"스키마 '{schema}'에 해당하는 평가 항목이 없습니다")

    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    label = run_name or source_label
    run_id = await eval_store.create_run(name, label, len(items))
    queue: asyncio.Queue = asyncio.Queue()
    state.eval_queues[run_id] = queue

    async def _progress(event: dict) -> None:
        await queue.put(event)

    async def _bg() -> None:
        try:
            await run_evaluation(
                run_id, items, orchestrator, eval_store,
                user_id=admin.id, on_progress=_progress, concurrency=concurrency,
            )
        except asyncio.CancelledError:
            pass
        finally:
            await asyncio.shield(queue.put(None))
            state.eval_queues.pop(run_id, None)
            state.eval_tasks.pop(run_id, None)

    state.eval_tasks[run_id] = asyncio.create_task(_bg())
    return {"run_id": run_id, "total": len(items)}


@router.get("/targets/{name}/eval/runs")
async def list_eval_runs(name: str, limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0)):
    """평가 이력 목록(최신순, 페이지 단위). 기본 10건 — 이력이 쌓여도 첫 페이지만
    보면 되게 한다. 이력 자체는 지우지 않는다(문서의 수치를 재확인하는 유일한 근거)."""
    eval_store = _require_eval_store()
    runs = await eval_store.list_runs(name, limit=limit, offset=offset)
    return {
        "total": await eval_store.count_runs(name),
        "limit": limit,
        "offset": offset,
        "items": [
            {"id": r.id, "run_name": r.run_name, "status": r.status, "total": r.total, "done": r.done,
             "correct_ex": r.correct_ex, "correct_em": r.correct_em, "ex_pct": r.ex_pct, "em_pct": r.em_pct,
             "correct_ex_official": r.correct_ex_official, "ex_official_pct": r.ex_official_pct,
             "created_at": r.created_at.isoformat() if r.created_at else None,
             "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in runs
        ]
    }


@router.get("/targets/{name}/eval/runs/{run_id}")
async def get_eval_run(name: str, run_id: int, limit: int = 100, offset: int = 0, only_wrong: bool = False):
    eval_store = _require_eval_store()
    run = await eval_store.get_run(run_id)
    if not run or run.target_name != name:
        raise HTTPException(404, "평가 실행 없음")
    items = await eval_store.get_items(run_id, limit=limit, offset=offset, only_wrong=only_wrong)
    defects = await _gold_defect_store().as_map(name)

    # "결함 제외 EX"는 부가 정보다 — run.correct_ex/ex_pct(strict EX)는 그대로 둔다.
    # 이 페이지가 보여주는 items 범위가 아니라 run 전체 기준으로 계산해야 의미가 있으므로
    # 전 항목을 다시 훑는다(30~500문항 규모라 비용이 문제되지 않는다).
    all_items = await eval_store.get_items(run_id, limit=10_000)
    scored = [it for it in all_items if (it.db_id, it.question_id) not in defects]
    adj_total = len(scored)
    adj_ex = sum(1 for it in scored if it.ex_pass)

    return {
        "run": {"id": run.id, "run_name": run.run_name, "status": run.status, "total": run.total, "done": run.done,
                "correct_ex": run.correct_ex, "correct_em": run.correct_em, "ex_pct": run.ex_pct, "em_pct": run.em_pct,
                "correct_ex_official": run.correct_ex_official, "ex_official_pct": run.ex_official_pct,
                "gold_defects": len(all_items) - adj_total,
                "adjusted_total": adj_total, "adjusted_ex": adj_ex,
                "adjusted_ex_pct": round(adj_ex / adj_total * 100, 2) if adj_total else 0.0},
        "items": [
            {"seq": it.seq, "question_id": it.question_id, "db_id": it.db_id, "difficulty": it.difficulty,
             "question": it.question, "evidence": it.evidence, "gold_sql": it.gold_sql, "pred_sql": it.pred_sql,
             "ex_pass": it.ex_pass, "em_pass": it.em_pass, "error": it.error, "elapsed_ms": it.elapsed_ms,
             "ex_official": it.ex_official, "guards_fired": it.guards_fired,
             "gold_defect": (
                 {"reason": d.reason, "evidence": d.evidence}
                 if (d := defects.get((it.db_id, it.question_id))) else None
             )}
            for it in items
        ],
    }


def _gold_defect_store():
    from pgxnl.agent.evaluation.store import GoldDefectStore
    from pgxnl.api.state import state

    if state.system_pool is None:
        raise HTTPException(503, "시스템 DB가 초기화되지 않았습니다")
    return GoldDefectStore(state.system_pool)


class GoldDefectBody(BaseModel):
    db_id: str = ""
    question_id: str
    reason: str
    evidence: str | None = None


@router.post("/targets/{name}/eval/runs/{run_id}/rescore-official")
async def rescore_eval_official(name: str, run_id: int):
    """끝난 run 의 공식 BIRD 점수(set 비교)를 저장된 pred/gold SQL 을 다시 실행해 채운다.
    모델은 부르지 않는다 — 대상 DB 에 질의만 다시 보낸다(문항당 2회)."""
    from pgxnl.agent.evaluation.bird import rescore_official
    from pgxnl.api.state import TargetNotFoundError, state

    eval_store = _require_eval_store()
    run = await eval_store.get_run(run_id)
    if run is None or run.target_name != name:
        raise HTTPException(404, "run을 찾을 수 없습니다")
    if run.status == "running":
        raise HTTPException(409, "진행 중인 run은 다시 채점할 수 없습니다")
    try:
        orchestrator = await state.get_orchestrator(name)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return await rescore_official(orchestrator, eval_store, run_id)


@router.get("/targets/{name}/eval/gold-defects")
async def list_gold_defects(name: str):
    defects = await _gold_defect_store().list_for(name)
    return {"items": [
        {"id": d.id, "db_id": d.db_id, "question_id": d.question_id,
         "reason": d.reason, "evidence": d.evidence} for d in defects
    ]}


@router.put("/targets/{name}/eval/gold-defects")
async def upsert_gold_defect(name: str, body: GoldDefectBody, admin: CurrentUser = Depends(require_admin)):
    defect_id = await _gold_defect_store().upsert(
        name, body.db_id, body.question_id, body.reason, body.evidence
    )
    return {"id": defect_id}


@router.delete("/targets/{name}/eval/gold-defects/{defect_id}")
async def delete_gold_defect(name: str, defect_id: int, admin: CurrentUser = Depends(require_admin)):
    if not await _gold_defect_store().delete(defect_id):
        raise HTTPException(404, "등록된 결함이 없습니다")
    return {"deleted": True}


@router.get("/targets/{name}/eval/runs/{run_id}/stream")
async def stream_eval_run(name: str, run_id: int):
    from pgxnl.api.state import state

    eval_store = _require_eval_store()
    queue = state.eval_queues.get(run_id)

    async def _gen():
        if queue is None:
            run = await eval_store.get_run(run_id)
            status = run.status if run else "error"
            yield {"data": json.dumps({"type": "done", "status": status})}
            return
        while True:
            event = await queue.get()
            if event is None:
                run = await eval_store.get_run(run_id)
                status = run.status if run else "done"
                yield {"data": json.dumps({"type": "done", "status": status})}
                return
            yield {"data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(_gen())


@router.post("/targets/{name}/eval/runs/{run_id}/cancel")
async def cancel_eval(name: str, run_id: int):
    from pgxnl.agent.evaluation.bird import request_cancel
    from pgxnl.api.state import state

    eval_store = _require_eval_store()
    request_cancel(run_id)
    task = state.eval_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        return {"ok": True, "message": f"run #{run_id} 강제 중단"}
    run = await eval_store.get_run(run_id)
    if run and run.status == "running":
        await eval_store.finish_run(run_id, "cancelled")
    return {"ok": True, "message": f"run #{run_id} 중단 처리됨"}


@router.delete("/targets/{name}/eval/runs/{run_id}")
async def delete_eval_run(name: str, run_id: int):
    eval_store = _require_eval_store()
    deleted = await eval_store.delete_run(run_id)
    if not deleted:
        raise HTTPException(404, "평가 실행 없음")
    return {"ok": True}


# ── 시스템 정보 ──────────────────────────────────────
@router.get("/system-info")
async def system_info():
    """관리 > 시스템 정보 — 시스템 DB·대상 DB 연결·LLM·임베딩·서버. 비밀값은 마스킹한다."""
    from pgxnl.api.state import state
    from pgxnl.api.system_info import collect_system_info

    return await collect_system_info(state)
