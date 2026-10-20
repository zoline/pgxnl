"""PostgreSQL 전용 커넥터 구현체.

design 문서 §3, §5.9 참고. 읽기전용 강제는 애플리케이션 레벨(ANTLR AST 검사,
pgxnl/agent/validation.py)과 DB 레벨(SET TRANSACTION READ ONLY, RLS) 이중으로 적용된다.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import asyncpg

from pgxnl.connectors.base import BaseConnector, ColumnMeta, IndexMeta, TableMeta

_SAFE_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def substitute_dsn_credentials(dsn: str, username: str, password: str) -> str:
    """DSN의 host:port/db는 유지하고 user:pass만 사용자별 자격증명으로 교체한다."""
    p = urlparse(dsn)
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}"
    return urlunparse(p._replace(netloc=netloc))



def _row_dict(record: Any) -> dict[str, Any]:
    """행을 dict 로. 이름이 같은 컬럼이 여럿이면(`SELECT AVG(a), AVG(b)` → 둘 다 avg) `dict(record)` 는
    뒤의 값만 남기고 앞을 버린다 — BIRD 채점에서 gold 가 컬럼 하나로 줄어 맞는 pred 가 오답 처리됐다
    (codebase_community 323, 2026-10-16). 두 번째부터 `이름#2` 처럼 이름을 바꿔 값을 모두 남긴다."""
    out: dict[str, Any] = {}
    for key, value in zip(record.keys(), record.values()):
        name, n = key, 2
        while name in out:
            name, n = f"{key}#{n}", n + 1
        out[name] = value
    return out

class PgConnector(BaseConnector):
    dialect = "postgresql"

    def __init__(self, dsn: str, *, readonly: bool = True, statement_timeout_ms: int = 30_000) -> None:
        super().__init__(dsn, readonly=readonly)
        self._pool: asyncpg.Pool | None = None
        self._statement_timeout_ms = statement_timeout_ms

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        """연결된 asyncpg 풀. pg_stats 등 raw 카탈로그 조회가 필요한 어댑터용.

        connect() 이전에 접근하면 AssertionError — 호출부가 connect() 이후에만
        사용하도록 보장해야 한다(Orchestrator._ensure_initialized 참고).
        """
        assert self._pool is not None, "connect()를 먼저 호출해야 합니다"
        return self._pool

    async def list_schemas(self) -> list[str]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
              AND schema_name NOT LIKE 'pg_toast%'
            ORDER BY schema_name
            """
        )
        return [r["schema_name"] for r in rows]

    async def list_tables(self, schema: str) -> list[TableMeta]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT c.relname AS table_name, obj_description(c.oid) AS comment
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = $1 AND c.relkind = 'r'
            ORDER BY c.relname
            """,
            schema,
        )
        return [
            TableMeta(schema=schema, name=r["table_name"], comment=r["comment"], columns=[], foreign_keys=[])
            for r in rows
        ]

    async def describe_table(self, schema: str, table: str) -> TableMeta:
        assert self._pool is not None
        col_rows = await self._pool.fetch(
            """
            SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS data_type,
                   col_description(a.attrelid, a.attnum) AS comment,
                   EXISTS (
                       SELECT 1 FROM pg_index i
                       WHERE i.indrelid = a.attrelid AND a.attnum = ANY(i.indkey) AND i.indisprimary
                   ) AS is_pk
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = $1 AND c.relname = $2 AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            schema,
            table,
        )
        fk_rows = await self._pool.fetch(
            """
            SELECT kcu.column_name, ccu.table_name AS ref_table, ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = $1 AND tc.table_name = $2
            """,
            schema,
            table,
        )
        columns = [
            ColumnMeta(name=r["name"], data_type=r["data_type"], comment=r["comment"], is_primary_key=r["is_pk"])
            for r in col_rows
        ]
        fks = [(r["column_name"], r["ref_table"], r["ref_column"]) for r in fk_rows]
        return TableMeta(schema=schema, name=table, comment=None, columns=columns, foreign_keys=fks)

    async def list_indexes(self, schema: str) -> list[IndexMeta]:
        assert self._pool is not None
        idx_rows = await self._pool.fetch(
            "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname=$1 ORDER BY tablename, indexname",
            schema,
        )
        pk_rows = await self._pool.fetch(
            """
            SELECT c.conname FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            WHERE n.nspname = $1 AND c.contype = 'p'
            """,
            schema,
        )
        pk_names = {r["conname"] for r in pk_rows}
        return [
            IndexMeta(
                schema=schema, table=r["tablename"], name=r["indexname"],
                is_primary=r["indexname"] in pk_names,
                is_unique="unique index" in r["indexdef"].lower(),
                definition=r["indexdef"],
            )
            for r in idx_rows
        ]

    async def explain(
        self, sql: str, *, analyze: bool = False, schema: str | None = None, timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """EXPLAIN (FORMAT JSON) 결과를 파싱된 dict로 반환한다.

        analyze=True면 실제로 쿼리를 실행한다 — execute_readonly와 동일하게
        READ ONLY 트랜잭션 안에서 실행되므로 DML/DDL은 DB 레벨에서 거부된다.
        target DB 커넥션 풀은 jsonb 코덱을 등록하지 않으므로(시스템 풀과 달리),
        "QUERY PLAN" 컬럼은 raw JSON 문자열로 돌아온다 — 여기서 직접 파싱한다.
        """
        clause = "ANALYZE true, BUFFERS true, " if analyze else ""
        explain_sql = f"EXPLAIN ({clause}FORMAT JSON) {sql.strip().rstrip(';')}"
        rows = await self.execute_readonly(explain_sql, timeout_seconds=timeout_seconds, schema=schema)
        if not rows:
            raise ValueError("EXPLAIN 결과가 비어 있습니다")
        raw = rows[0].get("QUERY PLAN")
        plan_data = json.loads(raw) if isinstance(raw, str) else raw
        root = plan_data[0] if isinstance(plan_data, list) else plan_data
        return {
            "plan": root.get("Plan", root),
            "planning_time": root.get("Planning Time"),
            "execution_time": root.get("Execution Time"),
            "analyzed": analyze,
        }

    async def execute_readonly(
        self, sql: str, *, row_limit: int | None = None, timeout_seconds: float | None = None,
        schema: str | None = None, params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """params: $1, $2 ... 자리표시자에 바인딩할 값. 값을 SQL 문자열에 이어붙이지
        않기 위한 것이다 — 사용자·모델이 만든 값을 그대로 넣으면 주입 위험이 있고,
        따옴표가 든 값에서 구문 오류가 난다."""
        assert self._pool is not None
        async with self._pool.acquire() as conn, conn.transaction(readonly=True):
            if timeout_seconds:
                await conn.execute(f"SET LOCAL statement_timeout = {int(timeout_seconds * 1000)}")
            if schema:
                if not _SAFE_IDENTIFIER.fullmatch(schema):
                    raise ValueError(f"올바르지 않은 스키마 이름: {schema!r}")
                # SET LOCAL은 이 트랜잭션(=이 호출)에만 적용되고 커밋/롤백 시 자동
                # 해제된다 — 커넥션이 풀로 반환된 뒤 다른 호출에 영향을 주지 않는다.
                # BIRD처럼 평가 문항마다 스키마(db_id)가 바뀌는 경우에 안전하게 쓸 수 있다.
                await conn.execute(f'SET LOCAL search_path TO "{schema}", public')
            query = sql
            if row_limit is not None:
                # 원본 SQL을 그대로 감싸는 서브쿼리로 행 수를 제한한다. 문자열로
                # "LIMIT n"을 바로 이어붙이면 원본에 이미 LIMIT이 있을 때
                # "LIMIT 5 LIMIT 50"처럼 구문 오류가 난다 — 서브쿼리 래핑은 원본이
                # 자체 LIMIT/ORDER BY를 갖고 있어도 항상 안전하다.
                inner = sql.strip().rstrip(";").strip()
                query = f"SELECT * FROM ({inner}) AS _pgxnl_limited LIMIT {row_limit}"
            rows = await conn.fetch(query, *(params or []))
            return [_row_dict(r) for r in rows]
