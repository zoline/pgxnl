"""DDL/통계 TTL 캐시. design 문서 §5.12 / 표 7(pgxnl_schema_cache).

data 컬럼은 JSONB이며, 시스템 DB 풀 생성 시 등록된 jsonb 코덱(main.py 참고)이
Python 객체 <-> JSON 문자열 변환을 자동으로 처리하므로 여기서는 json.dumps/loads를
직접 호출하지 않는다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import asyncpg


@dataclass
class CacheStats:
    total: int
    by_kind: dict[str, int]


class SchemaCache:
    """cache_key 접두어 규칙: ddl: / tables: / search: / stats:"""

    def __init__(self, pool: asyncpg.Pool, ttl_seconds: int) -> None:
        self._pool = pool
        self._ttl = ttl_seconds

    async def get(self, target_name: str, cache_key: str) -> Any | None:
        row = await self._pool.fetchrow(
            "SELECT data, cached_at FROM pgxnl_schema_cache WHERE target_name=$1 AND cache_key=$2",
            target_name,
            cache_key,
        )
        if row is None:
            return None
        age = time.time() - row["cached_at"].timestamp()
        if age > self._ttl:
            return None
        return row["data"]

    async def set(self, target_name: str, cache_key: str, data: Any) -> None:
        await self._pool.execute(
            """
            INSERT INTO pgxnl_schema_cache (target_name, cache_key, data, cached_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (target_name, cache_key)
            DO UPDATE SET data = EXCLUDED.data, cached_at = now()
            """,
            target_name,
            cache_key,
            data,
        )

    async def invalidate(self, target_name: str) -> None:
        await self._pool.execute("DELETE FROM pgxnl_schema_cache WHERE target_name=$1", target_name)

    async def stats(self, target_name: str) -> CacheStats:
        rows = await self._pool.fetch(
            "SELECT cache_key FROM pgxnl_schema_cache WHERE target_name=$1", target_name
        )
        by_kind: dict[str, int] = {}
        for r in rows:
            kind = r["cache_key"].split(":", 1)[0]
            by_kind[kind] = by_kind.get(kind, 0) + 1
        return CacheStats(total=len(rows), by_kind=by_kind)
