"""분석 API. design 문서 §4(질의 처리 흐름), §9(REST API) 참고."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from pgxnl.api.schema_browse import ExplainBody, browse_schema_data
from pgxnl.auth.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/api", tags=["analyze"])


class AnalyzeRequest(BaseModel):
    target: str
    question: str
    debug: bool = False
    schema_name: str = Field(default="public", alias="schema")
    # question과 별도 필드 — orchestrator.analyze()의 evidence 인자와 동일한 이유로
    # question 문자열에 미리 이어붙이지 않는다(질문 보강 재작성이 evidence를 지울 수 있음).
    evidence: str | None = None
    # 캐시를 끄고 파이프라인을 실제로 태우고 싶을 때 쓴다 — 용어집/규칙을 바꿔가며 그 효과를
    # 보려면 필수다(캐시 히트면 바꾼 설정이 SQL에 전혀 반영되지 않는다). BIRD 평가 하네스가
    # 같은 이유로 use_cache=False로 돈다.
    use_cache: bool = True

    model_config = {"populate_by_name": True}


@router.get("/targets")
async def list_targets(user: CurrentUser = Depends(get_current_user)):
    from pgxnl.api.state import state

    if state.target_store is None:
        raise HTTPException(503, "시스템 DB 미연결 — 대상 DB를 조회할 수 없습니다")
    records = await state.target_store.list_targets()
    return {"targets": [{"name": r.name, "dialect": r.dialect} for r in records]}


@router.get("/targets/{name}/schemas")
async def target_schemas(name: str, user: CurrentUser = Depends(get_current_user)):
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator_for_user(name, user.id)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"schemas": await orchestrator.list_schemas()}


@router.get("/targets/{name}/browse")
async def browse_target(name: str, search: str = "", user: CurrentUser = Depends(get_current_user)):
    """Schema 탐색 탭 — 대상 DB의 테이블/컬럼/PK/FK/인덱스 조회. 사용자별 DB 자격증명이
    있으면(pgxnl_user_credentials) 그 계정으로, 없으면 공유 계정으로 조회한다."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator_for_user(name, user.id)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return await browse_schema_data(orchestrator, search)


@router.get("/targets/{name}/join-graph")
async def target_join_graph(name: str, schema: str = "", user: CurrentUser = Depends(get_current_user)):
    """Schema 탐색의 ERD용 — 승인된(reviewed=true) JOIN 관계만 반환한다. 검토되지 않은
    후보는 신뢰할 수 없어 ERD에 섞지 않는다(§ JOIN 승인 워크플로와 동일한 기준)."""
    from pgxnl.agent.discovery.graph import list_edges
    from pgxnl.api.state import state

    if state.system_pool is None:
        raise HTTPException(503, "시스템 DB 미연결")
    edges = await list_edges(state.system_pool, name, only_reviewed=True, schema=schema or None)
    return {
        "edges": [
            {"schema_name": e.schema_name,
             "table_a": e.table_a, "column_a": e.column_a, "table_b": e.table_b, "column_b": e.column_b,
             "source": e.source, "confidence": e.confidence}
            for e in edges
        ]
    }


@router.get("/targets/{name}/design-lab")
async def target_design_lab(
    name: str, schema: str = Query(...), user: CurrentUser = Depends(get_current_user)
):
    """Design Lab — 스키마의 정규형을 검토한다(§Design Lab).

    전부 결정론적이다(LLM 호출 없음, 읽기 전용 SQL만). 자연어 질의가 **구조적으로**
    모호해지는 지점을 찾는 것이 목적이다 — 같은 개념이 여러 테이블에 사본으로 있고
    값까지 갈리면, 모델이 정답 논리를 알아도 다른 사본을 고르면 틀린다(실측: BIRD
    `california_schools` 30문항 중 12개가 그런 컬럼을 gold에서 쓴다).

    데이터를 훑으므로 큰 스키마에서는 느릴 수 있다 — 화면에서 스키마를 골라
    요청할 때만 계산하고 캐시하지 않는다(카탈로그·데이터가 바뀌면 결과도 바뀌므로).
    """
    from pgxnl.agent.designlab import analyze_schema
    from pgxnl.api.state import state

    # orchestrator를 그대로 넘긴다 — list_tables/describe_table/execute_readonly를
    # 공개 메서드로 갖고 있어 Design Lab의 Catalog 프로토콜을 만족한다. 커넥터를
    # 직접 꺼내 쓰면 초기화(connect) 책임까지 여기로 넘어온다.
    orchestrator = await state.get_orchestrator_for_user(name, user.id)
    report = await analyze_schema(orchestrator, target_name=name, schema=schema)
    return {
        "target": report.target_name,
        "schema": report.schema,
        "tables": report.tables,
        "findings": [
            {"kind": f.kind, "normal_form": f.normal_form, "severity": f.severity,
             "title": f.title, "detail": f.detail, "action": f.action,
             "tables": f.tables, "columns": f.columns}
            for f in sorted(report.findings,
                            key=lambda f: {"high": 0, "medium": 1, "info": 2}[f.severity])
        ],
        "duplicate_concepts": [
            {"concept": d.concept,
             "columns": [f"{t}.{c}" for t, c in d.columns],
             "canonical": d.canonical,
             "divergences": [
                 {"a": a, "b": b, "rows": n, "diff": diff, "pct": round(pct, 2)}
                 for a, b, n, diff, pct in d.divergences
             ]}
            for d in report.duplicate_concepts
        ],
        "mixed_grains": [
            {"table": g.table, "discriminator": g.discriminator,
             "partitions": [{"value": v, "rows": n, "empty_columns": empty}
                            for v, n, empty in g.partitions]}
            for g in report.mixed_grains
        ],
        "skipped": report.skipped,
    }


@router.get("/targets/{name}/design-lab/proposals")
async def target_design_lab_proposals(
    name: str, schema: str = Query(...), user: CurrentUser = Depends(get_current_user)
):
    """Design Lab findings 중 3NF 위반 2종(이행 종속·중복 개념)을 실제 DDL 제안으로
    바꾼다. `Finding.action`은 일부러 "지금 당장 할 수 있는 NL2SQL 대응"으로 좁혀
    뒀는데(§Design Lab), 이건 그 범위 밖의 것 — 스키마를 실제로 어떻게 바꾸면
    되는지를 보여준다. **보기 전용이다.** 여기서 실행하지 않는다 — 사람이 검토하고
    직접 실행한다.

    나머지 2종(반복 그룹·혼합 단위)은 사람 판단이 필요해 제안하지 않는다
    (propose.py 모듈 설명 참고).

    Design Lab 본체와 별도 호출인 이유 — 제안을 만들려면 관련 테이블을
    `describe_table` 로 다시 읽어야 해서(타입·FK 확인) 비용이 더 든다. 화면에서
    findings 를 먼저 보고, 필요할 때만("3NF 제안 보기") 이 호출을 하게 한다.
    """
    from pgxnl.agent.designlab import analyze_schema
    from pgxnl.agent.designlab.propose import propose_3nf
    from pgxnl.api.state import state

    orchestrator = await state.get_orchestrator_for_user(name, user.id)
    report = await analyze_schema(orchestrator, target_name=name, schema=schema)
    proposals = await propose_3nf(report, orchestrator)
    return {
        "target": report.target_name,
        "schema": report.schema,
        "proposals": [
            {"finding_title": p.finding_title, "kind": p.kind, "summary": p.summary,
             "ddl": p.ddl, "caveats": p.caveats, "detail": p.detail}
            for p in proposals
        ],
    }


@router.get("/targets/{name}/physical-lab")
async def target_physical_lab(
    name: str, schema: str = Query(...), user: CurrentUser = Depends(get_current_user)
):
    """Physical Lab — 스키마의 물리 상태(공간·죽은 행·VACUUM·인덱스)를 본다.

    Design Lab 의 짝이다. 저쪽이 논리 구조를 보고 이쪽이 물리 상태를 본다. 규칙은
    같다 — 결정론적이고(LLM 호출 없음) 읽기 전용이며, 요청할 때만 계산하고 캐시하지
    않는다(카탈로그가 바뀌면 결과도 바뀐다).

    판정하지 않고 근거를 함께 돌려준다. 특히 `stats_reset` 이 그렇다 — `idx_scan=0`
    은 "안 쓰이는 인덱스"가 아니라 "통계를 지운 뒤로 안 쓰인" 것이고, 그 구분 없이
    지우면 멀쩡한 인덱스를 지운다.
    """
    from pgxnl.agent.physicallab import analyze_physical, human_bytes
    from pgxnl.api.state import state

    orchestrator = await state.get_orchestrator_for_user(name, user.id)
    try:
        report = await analyze_physical(orchestrator, target_name=name, schema=schema)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    def iso(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    return {
        "target": report.target_name,
        "schema": report.schema,
        "total_bytes": report.total_bytes,
        "total_human": human_bytes(report.total_bytes),
        "stats_reset": iso(report.stats_reset),
        "tables": [
            {**t, "total_human": human_bytes(t.get("total_bytes")),
             "heap_human": human_bytes(t.get("heap_bytes")),
             "index_human": human_bytes(t.get("index_bytes")),
             "toast_human": human_bytes(t.get("toast_bytes"))}
            for t in report.tables
        ],
        "bloat": [
            {**b, "dead_pct": float(b.get("dead_pct") or 0),
             "last_vacuum": iso(b.get("last_vacuum")),
             "last_autovacuum": iso(b.get("last_autovacuum")),
             "last_analyze": iso(b.get("last_analyze")),
             "last_autoanalyze": iso(b.get("last_autoanalyze"))}
            for b in report.bloat
        ],
        "indexes": [
            {**i, "size_human": human_bytes(i.get("bytes"))} for i in report.indexes
        ],
        "findings": [
            {"kind": f.kind, "severity": f.severity, "title": f.title,
             "detail": f.detail, "action": f.action, "tables": f.tables}
            for f in report.findings
        ],
    }


@router.get("/targets/{name}/verified-queries")
async def list_verified_queries(
    name: str, schema_name: str | None = Query(None), table: str | None = Query(None),
    q: str | None = Query(None), approved_only: bool = False, limit: int = 50, offset: int = 0,
    user: CurrentUser = Depends(get_current_user),
):
    """유사 쿼리 탐색 — 승인된 사용례를 조회한다. **일반 사용자에게 열려 있다**
    (2026-09-15) — 등록·수정·승인·삭제는 admin 전용(routes_admin.py)이지만, 조회는
    이 도구를 실제로 쓸 사람(SQL 미숙련 사용자)에게 막아둘 이유가 없다. 승인 절차의
    본체(설명이 맞는지 확인)는 등록 단계에서 이미 끝나 있다.

    `q`가 있으면 거르지 않고 **순위만** 매긴다 — 임계값을 두지 않는다. 사람이
    목록에서 고르므로 빗나간 항목이 섞이는 비용이 낮고, 반대로 임계값 때문에
    목록이 비면 화면이 쓸모없어진다. 시맨틱 캐시가 임계값을 두는 것과 정반대의
    이유다(저쪽은 자동으로 하나를 골라 내보낸다).

    `approved_only` 기본값이 False 이지만 **일반 사용자 화면(Query)은 항상
    approved_only=true 로 호출한다** — 미승인 항목(설명이 아직 검증 안 됨)을
    일반 사용자에게 보여주면 안 된다. 서버가 강제하지 않는 이유는 admin 화면(SQL
    수집)도 같은 엔드포인트로 미승인 항목까지 봐야 하기 때문이다.
    """
    from pgxnl.api.state import state

    store = state.verified_store
    if store is None:
        raise HTTPException(503, "시스템 DB 미연결")
    q_embedding = None
    if q and state.embed_fn is not None:
        try:
            q_embedding = await state.embed_fn(q)
        except Exception:  # noqa: BLE001
            pass  # 임베딩은 순위 재료일 뿐이다. 없으면 trgm으로 내려앉는다

    total, items = await store.list(
        name, schema_name=schema_name, table=table, q=q, q_embedding=q_embedding,
        approved_only=approved_only, limit=limit, offset=offset,
    )
    return {
        "total": total,
        "ranked_by": ("임베딩" if q_embedding else "어휘") if q else None,
        "items": [
            {
                "id": e.id, "schema_name": e.schema_name, "question": e.question,
                "sql": e.sql_text, "tables_used": e.tables_used, "has_pii": e.has_pii,
                "approved": e.approved, "score": e.score,
                "created_at": e.created_at.isoformat(),
            }
            for e in items
        ],
    }


@router.get("/targets/{name}/design-lab/glossary-suggestions")
async def target_glossary_suggestions(
    name: str, schema: str = Query(...), user: CurrentUser = Depends(get_current_user)
):
    """Design Lab이 찾은 구조에서 용어집 항목을 유도해 제안한다.

    등록하지는 않는다 — 관리자가 검토하고 고르는 것이 워크플로다(§Design Lab).
    이미 같은 컬럼에 등록된 항목이 있으면 `existing`에 실어 보내 **덮어쓸지
    건너뛸지** 고르게 한다. `for_table()`이 컬럼 중복을 막지 않으므로, 모르고
    등록하면 같은 컬럼에 정의가 두 개 실린다(실측: 손수 15건과 자동 20건이 9건 겹쳤다).
    """
    from pgxnl.agent.designlab import analyze_schema
    from pgxnl.agent.designlab.suggest import suggest_glossary
    from pgxnl.api.state import state

    orchestrator = await state.get_orchestrator_for_user(name, user.id)
    report = await analyze_schema(orchestrator, target_name=name, schema=schema)
    suggestions = await suggest_glossary(orchestrator, schema=schema, report=report)

    existing: dict[tuple[str, str], Any] = {}
    if state.glossary_store is not None:
        for e in await state.glossary_store.list_all(name, schema):
            existing[(e.table_name or "", (e.column_name or "").lower())] = e

    def payload(s):
        cur = existing.get((s.table_name, s.column_name.lower()))
        return {
            "kind": s.kind, "schema_name": s.schema_name, "table_name": s.table_name,
            "column_name": s.column_name, "term": s.term, "definition": s.definition,
            "source": s.source, "rationale": s.rationale,
            "existing": None if cur is None else {
                "id": cur.id, "term": cur.term, "definition": cur.definition,
                "source": cur.source,
            },
        }

    return {
        "target": name, "schema": schema,
        "suggestions": [payload(s) for s in suggestions],
    }


@router.post("/targets/{name}/explain")
async def explain_target_query(name: str, body: ExplainBody, user: CurrentUser = Depends(get_current_user)):
    """실행계획 탭 — EXPLAIN (FORMAT JSON) [ANALYZE]. READ ONLY 트랜잭션 내에서 실행되므로
    ANALYZE 모드에서도 DML/DDL은 DB 레벨에서 거부된다."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator_for_user(name, user.id)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        return await orchestrator.explain(
            body.sql, analyze=body.analyze, schema=body.schema_name, timeout_seconds=60,
        )
    except Exception as exc:
        raise HTTPException(400, f"EXPLAIN 실행 오류: {exc}") from exc


class SqlTuningBody(BaseModel):
    sql: str
    schema_name: str = Field(default="public", alias="schema")
    debug: bool = False

    model_config = {"populate_by_name": True}


@router.post("/targets/{name}/sql-tuning")
async def sql_tuning(name: str, body: SqlTuningBody, user: CurrentUser = Depends(get_current_user)):
    """SQL 튜닝 탭 — EXPLAIN ANALYZE 결과를 LLM에게 보여 병목 분석/재작성 제안/인덱스
    제안을 받는다. explain()과 마찬가지로 실제 쿼리를 실행하므로(ANALYZE) READ ONLY
    트랜잭션 안에서만 동작한다. /analyze와 동일한 SSE 스트리밍 패턴 — 질문분석
    화면처럼 단계별 진행 상황(status)을 먼저 보여주고 마지막에 answer 이벤트로 마감."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator_for_user(name, user.id)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    queue: asyncio.Queue = asyncio.Queue()

    async def on_step(message: str) -> None:
        await queue.put({"event": "status", "data": json.dumps({"message": message}, ensure_ascii=False)})

    async def run() -> None:
        try:
            answer = await orchestrator.analyze_sql_tuning(
                body.sql, schema=body.schema_name, on_step=on_step, debug=body.debug,
            )
            await queue.put({"event": "answer", "data": json.dumps({"answer": answer}, ensure_ascii=False)})
        except Exception as exc:  # noqa: BLE001 — 스트림 소비자에게 오류를 전달
            await queue.put({"event": "error", "data": json.dumps({"message": str(exc)}, ensure_ascii=False)})
        finally:
            await queue.put(None)

    async def event_stream():
        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            task.cancel()

    return EventSourceResponse(event_stream())


class DesignLabLlmReviewBody(BaseModel):
    schema_name: str = Field(default="public", alias="schema")
    debug: bool = False
    #: "findings" — 결정론적 검토 결과를 근거로 / "schema_only" — 스키마 정의만으로
    mode: Literal["findings", "schema_only"] = "findings"

    model_config = {"populate_by_name": True}


@router.post("/targets/{name}/design-lab/llm-review")
async def design_lab_llm_review(name: str, body: DesignLabLlmReviewBody, user: CurrentUser = Depends(get_current_user)):
    """Design Lab 옆의 "LLM 검토" 버튼 — 결정론적 분석 결과를 LLM에게 보여주고
    자유 의견을 받는다. **참고용이며 확정된 제안이 아니다** — Design Lab 본체와
    3NF 제안(propose.py)은 그대로 결정론적으로 남아 있고, 이건 그 옆에 별도로
    보여주는 의견일 뿐이다. SQL 튜닝과 같은 SSE 스트리밍 패턴, 같은 LLM 스테이지
    (`sql_tuning`)를 재사용한다(신규 모델 설정 없음, 사용자 요청)."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator_for_user(name, user.id)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    queue: asyncio.Queue = asyncio.Queue()

    async def on_step(message: str) -> None:
        await queue.put({"event": "status", "data": json.dumps({"message": message}, ensure_ascii=False)})

    async def run() -> None:
        try:
            result = await orchestrator.analyze_design_lab_review(
                body.schema_name, on_step=on_step, debug=body.debug, mode=body.mode,
            )
            await queue.put({"event": "answer", "data": json.dumps(result, ensure_ascii=False)})
        except Exception as exc:  # noqa: BLE001 — 스트림 소비자에게 오류를 전달
            await queue.put({"event": "error", "data": json.dumps({"message": str(exc)}, ensure_ascii=False)})
        finally:
            await queue.put(None)

    async def event_stream():
        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            task.cancel()

    return EventSourceResponse(event_stream())


@router.post("/analyze")
async def analyze(req: AnalyzeRequest, user: CurrentUser = Depends(get_current_user)):
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator_for_user(req.target, user.id)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    queue: asyncio.Queue = asyncio.Queue()

    async def on_step(message: str) -> None:
        await queue.put({"event": "status", "data": json.dumps({"message": message}, ensure_ascii=False)})

    async def run() -> None:
        try:
            result = await orchestrator.analyze(
                req.question, user_id=user.id, on_step=on_step, debug=req.debug, schema=req.schema_name,
                evidence=req.evidence, use_cache=req.use_cache,
            )
            await queue.put({
                "event": "answer",
                "data": json.dumps(
                    {"answer": result.answer, "sql_steps": result.sql_steps, "from_cache": result.from_cache},
                    ensure_ascii=False, default=str,
                ),
            })
        except Exception as exc:  # noqa: BLE001 — 스트림 소비자에게 오류를 전달
            await queue.put({"event": "error", "data": json.dumps({"message": str(exc)}, ensure_ascii=False)})
        finally:
            await queue.put(None)

    async def event_stream():
        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            task.cancel()

    return EventSourceResponse(event_stream())


class AnalyzeSqlRequest(BaseModel):
    target: str
    sql: str
    schema_name: str = "public"


@router.post("/analyze/sql")
async def analyze_sql(req: AnalyzeSqlRequest, user: CurrentUser = Depends(get_current_user)):
    """"Query" 화면의 SQL 직접 입력 모드 — 자연어 경로와 같은 검증 계층을 거치되
    LLM ReAct 루프/요약 없이 곧바로 실행 결과(rows)를 반환한다."""
    from pgxnl.api.state import TargetNotFoundError, state

    try:
        orchestrator = await state.get_orchestrator_for_user(req.target, user.id)
    except TargetNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    try:
        return await orchestrator.run_sql(req.sql, user_id=user.id, schema=req.schema_name)
    except Exception as exc:
        raise HTTPException(400, f"SQL 실행 오류: {exc}") from exc


@router.get("/status")
async def system_status(user: CurrentUser = Depends(get_current_user)):
    """사이드바 상태 줄 — 연결 여부·모델명만(DSN·경로 없음). 30초 동안 결과를 재사용한다."""
    from pgxnl.api.state import state
    from pgxnl.api.system_info import collect_status

    return await collect_status(state)
