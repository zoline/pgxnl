"""collect_stats 도구. design 문서 §5.3, §5.7 / ADR-0007 참고.

1차: PgStatsAdapter로 pg_stats 재사용 (저비용). 2차: ANALYZE 미실행이거나 통계가
없는 컬럼만 직접 샘플링으로 폴백. 결과는 SchemaCache에 TTL 캐싱된다.
"""
from __future__ import annotations

from dataclasses import asdict

from pgxnl.agent.stats.base import ColumnStats, StatsAdapter
from pgxnl.cache.schema import SchemaCache
from pgxnl.connectors.postgresql import PgConnector


async def collect_stats(
    conn: PgConnector, stats_adapter: StatsAdapter, cache: SchemaCache,
    target_name: str, schema: str, table: str, column: str, *, top_n: int = 20,
) -> dict:
    cache_key = f"stats:{schema}.{table}.{column}"
    cached = await cache.get(target_name, cache_key)
    if cached is not None:
        return cached

    stats = await stats_adapter.get_column_stats(schema, table, column)
    if stats is None:
        stats = await _direct_sample_stats(conn, schema, table, column, top_n=top_n)

    result = asdict(stats)
    await cache.set(target_name, cache_key, result)
    return result


async def _direct_sample_stats(
    conn: PgConnector, schema: str, table: str, column: str, *, top_n: int
) -> ColumnStats:
    rows = await conn.execute_readonly(
        f'''
        SELECT "{column}" AS v, count(*) AS c
        FROM "{schema}"."{table}"
        GROUP BY "{column}"
        ORDER BY c DESC
        LIMIT {top_n}
        ''',
        timeout_seconds=10,
    )
    total_row = await conn.execute_readonly(f'SELECT count(*) AS n FROM "{schema}"."{table}"')
    total = total_row[0]["n"] if total_row else 0
    return ColumnStats(
        n_distinct=None,
        null_frac=None,
        most_common_values=[r["v"] for r in rows],
        most_common_freqs=[r["c"] / total if total else 0.0 for r in rows],
        histogram_bounds=[],
        source="direct_sample",
    )
