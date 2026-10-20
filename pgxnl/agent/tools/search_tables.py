"""search_tables 도구. design 문서 §5.7 참고. 결과는 SchemaCache에 TTL 캐싱된다."""
from __future__ import annotations

from pgxnl.cache.schema import SchemaCache
from pgxnl.connectors.postgresql import PgConnector


async def search_tables(
    conn: PgConnector, cache: SchemaCache, target_name: str, schema: str, keyword: str
) -> list[dict]:
    cache_key = f"search:{keyword.lower()}"
    cached = await cache.get(target_name, cache_key)
    if cached is not None:
        return cached

    tables = await conn.list_tables(schema)
    matched = [
        {"schema": t.schema, "table": t.name, "comment": t.comment}
        for t in tables
        if keyword.lower() in t.name.lower() or (t.comment and keyword.lower() in t.comment.lower())
    ]
    await cache.set(target_name, cache_key, matched)
    return matched
