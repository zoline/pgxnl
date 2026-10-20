"""SQL statement 수집. pg_stat_statements 재사용 또는 파일 업로드.

수집된 SQL은 pgxnl_sql_statements에 저장되고, 파싱된 JOIN 조건은 부산물로
pgxnl_join_candidates에 함께 적재된다(source='collected') — join_history.py의
persist_candidates를 그대로 재사용한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg

from pgxnl.agent.discovery.join_history import (
    JoinCandidate,
    persist_candidates,
    references_only_internal,
)
from pgxnl.parsing.base import SqlParser


@dataclass
class SqlStatementRecord:
    target_name: str
    sql_hash: str
    sql_text: str
    sql_type: str = "other"
    call_count: int = 1
    total_time_ms: float = 0.0
    mean_time_ms: float = 0.0
    tables_used: list[str] = field(default_factory=list)
    source: str = "manual"
    collected_at: datetime | None = None
    id: int | None = None


class CollectionSummary:
    def __init__(self) -> None:
        self.total = 0
        self.inserted = 0
        self.errors = 0
        self.messages: list[str] = []

    def as_dict(self) -> dict:
        return {"total": self.total, "inserted": self.inserted, "errors": self.errors, "messages": self.messages}


class SqlStatementStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert_batch(self, statements: list[SqlStatementRecord]) -> int:
        count = 0
        for s in statements:
            await self._pool.execute(
                """
                INSERT INTO pgxnl_sql_statements
                    (target_name, sql_hash, sql_text, sql_type, call_count,
                     total_time_ms, mean_time_ms, tables_used, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (target_name, sql_hash) DO UPDATE SET
                    sql_text      = EXCLUDED.sql_text,
                    sql_type      = EXCLUDED.sql_type,
                    call_count    = pgxnl_sql_statements.call_count + EXCLUDED.call_count,
                    total_time_ms = pgxnl_sql_statements.total_time_ms + EXCLUDED.total_time_ms,
                    mean_time_ms  = (pgxnl_sql_statements.total_time_ms + EXCLUDED.total_time_ms)
                                    / NULLIF(pgxnl_sql_statements.call_count + EXCLUDED.call_count, 0),
                    tables_used   = EXCLUDED.tables_used,
                    collected_at  = now()
                """,
                s.target_name, s.sql_hash, s.sql_text, s.sql_type, s.call_count,
                s.total_time_ms, s.mean_time_ms, json.dumps(s.tables_used), s.source,
            )
            count += 1
        return count

    async def list_by_target(
        self, target_name: str, *, sql_type: str | None = None, limit: int = 200, offset: int = 0
    ) -> list[SqlStatementRecord]:
        if sql_type:
            rows = await self._pool.fetch(
                """
                SELECT * FROM pgxnl_sql_statements WHERE target_name = $1 AND sql_type = $2
                ORDER BY call_count DESC LIMIT $3 OFFSET $4
                """,
                target_name, sql_type, limit, offset,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM pgxnl_sql_statements WHERE target_name = $1 ORDER BY call_count DESC LIMIT $2 OFFSET $3",
                target_name, limit, offset,
            )
        return [_to_record(r) for r in rows]

    async def count(self, target_name: str) -> int:
        row = await self._pool.fetchrow(
            "SELECT count(*) AS n FROM pgxnl_sql_statements WHERE target_name = $1", target_name
        )
        return row["n"]

    async def delete_target(self, target_name: str) -> int:
        rows = await self._pool.fetch(
            "DELETE FROM pgxnl_sql_statements WHERE target_name = $1 RETURNING id", target_name
        )
        return len(rows)


def _to_record(r: asyncpg.Record) -> SqlStatementRecord:
    d = dict(r)
    tables = d.pop("tables_used")
    if isinstance(tables, str):
        tables = json.loads(tables)
    return SqlStatementRecord(tables_used=tables, **d)


def _sql_hash(sql: str) -> str:
    return hashlib.md5(sql.strip().lower().encode()).hexdigest()


def _build_record_and_joins(
    sql_text: str, parser: SqlParser, target_name: str, *, call_count: int, total_time_ms: float, source: str,
) -> tuple[SqlStatementRecord, list[JoinCandidate]] | None:
    parsed = parser.parse(sql_text)
    if not parsed.is_well_formed:
        # 불완전한 트리에서 뽑은 테이블/조인은 없는 관계를 학습시킨다 — 건너뛴다.
        return None
    if references_only_internal(parsed.referenced_tables):
        return None
    record = SqlStatementRecord(
        target_name=target_name,
        sql_hash=_sql_hash(sql_text),
        sql_text=sql_text,
        sql_type=parsed.kind.value,
        call_count=call_count,
        total_time_ms=total_time_ms,
        mean_time_ms=total_time_ms / call_count if call_count else 0.0,
        tables_used=parsed.referenced_tables,
        source=source,
    )
    candidates = [
        JoinCandidate(j.table_a, j.column_a, j.table_b, j.column_b, calls=call_count, source="collected")
        for j in parsed.joins
    ]
    return record, candidates


async def collect_from_pg_stat_statements(
    target_conn: Any, target_name: str, parser: SqlParser, store: SqlStatementStore, system_pool: asyncpg.Pool,
    *, min_calls: int = 1, limit: int = 1000,
) -> CollectionSummary:
    summary = CollectionSummary()
    try:
        rows = await target_conn.execute_readonly(
            f"""
            SELECT query, calls, total_exec_time FROM pg_stat_statements
            WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
              AND calls >= {int(min_calls)} AND query ILIKE 'SELECT%'
              AND query NOT ILIKE '%information_schema%'
              AND query NOT ILIKE '%pg_catalog%'
              AND query NOT ILIKE '%pg_stat_statements%'
              AND query NOT ILIKE '%pgxnl\\_%' ESCAPE '\\'
            ORDER BY total_exec_time DESC LIMIT {int(limit)}
            """
        )
    except Exception as exc:  # noqa: BLE001
        summary.messages.append(f"pg_stat_statements 접근 실패: {exc}")
        return summary

    records: list[SqlStatementRecord] = []
    all_candidates: list[JoinCandidate] = []
    for row in rows:
        sql_text = row.get("query") or ""
        if not sql_text.strip():
            continue
        summary.total += 1
        try:
            result = _build_record_and_joins(
                sql_text, parser, target_name,
                call_count=int(row.get("calls") or 1),
                total_time_ms=float(row.get("total_exec_time") or 0),
                source="pg_stat_statements",
            )
            if result is None:  # 내부 카탈로그만 참조하는 쿼리 — 수집 대상 아님
                continue
            record, candidates = result
            records.append(record)
            all_candidates.extend(candidates)
        except Exception as exc:  # noqa: BLE001 - 파싱 실패한 쿼리는 건너뛴다
            summary.errors += 1
            summary.messages.append(str(exc))

    summary.inserted = await store.upsert_batch(records)
    if all_candidates:
        await persist_candidates(system_pool, target_name, all_candidates)
    summary.messages.append(f"{summary.inserted}개 저장, JOIN 후보 {len(all_candidates)}개")
    return summary


def _parse_file_items(content: bytes, filename: str) -> list[dict]:
    text = content.decode("utf-8", errors="replace")
    data = json.loads(text)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("statements") or data.get("queries") or []
    else:
        raise ValueError(f"지원하지 않는 파일 구조: {type(data)}")

    result = []
    for item in items:
        if isinstance(item, str):
            result.append({"sql": item, "calls": 1, "total_ms": 0.0})
        elif isinstance(item, dict):
            sql = item.get("sql") or item.get("query") or ""
            if sql:
                result.append({
                    "sql": sql,
                    "calls": int(item.get("calls") or item.get("count") or 1),
                    "total_ms": float(item.get("total_ms") or item.get("elapsed_ms") or 0),
                })
    return result


async def collect_from_file(
    content: bytes, filename: str, target_name: str, parser: SqlParser, store: SqlStatementStore,
    system_pool: asyncpg.Pool,
) -> CollectionSummary:
    summary = CollectionSummary()
    try:
        items = _parse_file_items(content, filename)
    except Exception as exc:  # noqa: BLE001
        summary.messages.append(f"파일 파싱 실패: {exc}")
        return summary

    records: list[SqlStatementRecord] = []
    all_candidates: list[JoinCandidate] = []
    for item in items:
        summary.total += 1
        try:
            result = _build_record_and_joins(
                item["sql"], parser, target_name,
                call_count=item["calls"], total_time_ms=item["total_ms"], source=f"file:{filename}",
            )
            if result is None:  # 내부 카탈로그만 참조하는 쿼리 — 수집 대상 아님
                continue
            record, candidates = result
            records.append(record)
            all_candidates.extend(candidates)
        except Exception as exc:  # noqa: BLE001
            summary.errors += 1
            summary.messages.append(str(exc))

    summary.inserted = await store.upsert_batch(records)
    if all_candidates:
        await persist_candidates(system_pool, target_name, all_candidates)
    summary.messages.append(f"{summary.inserted}개 저장, JOIN 후보 {len(all_candidates)}개")
    return summary
