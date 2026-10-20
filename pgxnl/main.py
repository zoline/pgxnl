"""FastAPI 엔트리포인트. design 문서 §3(시스템 아키텍처) 참고.

uvicorn pgxnl.main:app --port 8100 로 실행.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pgxnl import __version__
from pgxnl.agent.discovery.statements import SqlStatementStore
from pgxnl.governance.verified_queries import VerifiedQueryStore
from pgxnl.agent.evaluation.store import EvalStore
from pgxnl.api.llm_profiles import LlmProfileStore
from pgxnl.api.routes_admin import router as admin_router
from pgxnl.api.routes_analyze import router as analyze_router
from pgxnl.api.routes_auth import router as auth_router
from pgxnl.api.state import create_llm_client, state
from pgxnl.api.targets import TargetStore
from pgxnl.auth.store import UserStore
from pgxnl.cache.schema import SchemaCache
from pgxnl.cache.semantic import SemanticCache
from pgxnl.governance.glossary import GlossaryStore
from pgxnl.governance.rules import SqlRuleStore
from pgxnl.llm.embeddings import create_embed_fn
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser
from pgxnl.settings import settings

logger = logging.getLogger(__name__)

_SCHEMA_SQL = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
_STATIC = Path(__file__).resolve().parent / "api" / "static"
_ADMIN_USERNAME = "pgxnl"


async def _apply_schema(pool: asyncpg.Pool) -> None:
    ddl = _SCHEMA_SQL.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(ddl)


async def _register_codecs(conn: asyncpg.Connection) -> None:
    """jsonb/json 컬럼을 Python dict/list로 자동 변환.

    등록 후에는 저장소 계층(cache/schema.py, cache/schema_vector.py, cache/semantic.py,
    governance/rules.py)에서 json.dumps/loads를 직접 호출하지 않는다 — 이중 인코딩 방지.
    """
    for typename in ("json", "jsonb"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        state.system_pool = await asyncpg.create_pool(
            settings.system_pg_dsn, min_size=1, max_size=settings.pg_pool_size, init=_register_codecs,
        )
        await _apply_schema(state.system_pool)
    except Exception as exc:  # noqa: BLE001 — 시스템 DB 없이도 프로세스는 뜨게 두고 /healthz로 상태 노출
        logger.warning("시스템 PostgreSQL 연결/스키마 적용 실패: %s", exc)
        state.system_pool = None

    state.llm = create_llm_client(settings)
    state.parser = AntlrPostgresParser()

    if state.system_pool is not None:
        state.user_store = UserStore(state.system_pool, settings.secret_key)
        state.target_store = TargetStore(state.system_pool, settings.secret_key)
        state.glossary_store = GlossaryStore(state.system_pool)
        state.rule_store = SqlRuleStore(state.system_pool)
        state.schema_cache = SchemaCache(state.system_pool, settings.schema_cache_ttl)
        state.statement_store = SqlStatementStore(state.system_pool)
        state.verified_store = VerifiedQueryStore(state.system_pool)
        state.eval_store = EvalStore(state.system_pool)
        state.llm_profile_store = LlmProfileStore(state.system_pool, settings.secret_key)

        embed_fn = create_embed_fn(settings, state.llm)
        state.embed_fn = embed_fn
        if settings.cache_enabled:
            state.semantic_cache = SemanticCache(
                state.system_pool, embed_fn,
                trgm_threshold=settings.cache_similarity_threshold,
                embedding_threshold=settings.cache_embedding_threshold,
                embedding_enabled=settings.cache_embedding_enabled,
                ttl_seconds=settings.cache_ttl_seconds,
            )

        api_key = await state.user_store.bootstrap_admin(_ADMIN_USERNAME, settings.admin_initial_password)
        if api_key:
            logger.warning(
                "admin 계정이 생성되었습니다. username=%s api_key=%s (다시 표시되지 않습니다)",
                _ADMIN_USERNAME, api_key,
            )

    yield

    for orchestrator in state.orchestrators.values():
        await orchestrator._conn.close()
    if state.system_pool is not None:
        await state.system_pool.close()


app = FastAPI(title="pgxnl", version=__version__, lifespan=lifespan)

app.include_router(auth_router)
app.include_router(analyze_router)
app.include_router(admin_router)

# ERD 드래그/커넥터용 jsPlumb 등, index.html이 참조하는 벤더 자산 서빙.
# index.html 자체는 "/"에서 단일 파일로 내려가므로(위 index() 참고) 이 mount는
# /static/vendor/... 자산 전용이다.
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "system_db": state.system_pool is not None}


@app.get("/")
async def index() -> FileResponse:
    # no-cache: 브라우저가 **재검증 없이** 캐시를 쓰지 않게 한다. 파일이 자주 바뀌는데
    # (UI는 한 파일이라 무엇을 고쳐도 이 응답이 바뀐다) 낡은 판이 물리면 화면이
    # 이상하게 보이고 새로고침 전까지 그대로다. ETag가 있으므로 내용이 같으면
    # 304로 끝나 비용은 거의 없다.
    return FileResponse(
        _STATIC / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pgxnl.main:app", host=settings.api_host, port=settings.api_port, workers=1, reload=True)
