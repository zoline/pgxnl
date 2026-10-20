"""pg_stats 재사용 어댑터. design 문서 §5.3 / ADR-0007 참고.

별도 배치 잡으로 값 예시를 수집하는 대신, PostgreSQL 옵티마이저가 ANALYZE 시점에
이미 수집해둔 통계(n_distinct, most_common_vals, histogram_bounds)를 그대로
재사용한다. 표본 기반이라 완전하지 않고(최대 100개 MCV), pg_stats 조회 자체에
대상 테이블 읽기 권한이 필요하다.
"""
from __future__ import annotations

from pgxnl.agent.stats.base import ColumnStats, StatsAdapter
from pgxnl.connectors.postgresql import PgConnector


class PgStatsAdapter(StatsAdapter):
    """대상 DB 자신의 pg_stats 카탈로그를 읽는다 — 시스템 DB가 아니라 target
    커넥터의 풀을 사용해야 한다. connector.pool은 connect() 이후에만 접근
    가능하므로, 풀을 미리 캡처하지 않고 호출 시점에 지연 조회한다."""

    def __init__(self, connector: PgConnector) -> None:
        self._connector = connector

    @property
    def _pool(self):
        return self._connector.pool

    async def get_column_stats(self, schema: str, table: str, column: str) -> ColumnStats | None:
        # most_common_vals/histogram_bounds는 `anyarray`라 asyncpg가 결과 타입을 결정하지
        # 못하고 `InternalClientError: could not resolve query result and/or argument types`
        # 로 던진다 — 이 도구가 통계를 한 번도 돌려주지 못한 원인이었다(2026-09-07 실측:
        # 어떤 컬럼으로 호출해도 실패, `_direct_sample_stats` 폴백은 None일 때만 도는데
        # 예외가 나므로 거기까지도 못 갔다). ::text로 캐스팅해 받고 ColumnStats에서 푼다.
        row = await self._pool.fetchrow(
            """
            SELECT n_distinct, null_frac, most_common_vals::text AS most_common_vals,
                   most_common_freqs, histogram_bounds::text AS histogram_bounds
            FROM pg_stats
            WHERE schemaname = $1 AND tablename = $2 AND attname = $3
            """,
            schema,
            table,
            column,
        )
        if row is None or row["most_common_vals"] is None:
            return None
        return ColumnStats.from_pg_stats(dict(row))

    async def get_null_frac(self, schema: str, table: str, column: str) -> float | None:
        """pg_stats에서 null_frac만 읽는다.

        `get_column_stats`의 SELECT 목록에는 `most_common_vals`/`histogram_bounds`가 있는데,
        이 둘은 `anyarray`라 asyncpg가 결과 타입을 결정하지 못하고
        `InternalClientError: could not resolve query result and/or argument types`로 던진다
        (BIRD 대상 DB에서 실측). null_frac은 real 스칼라라 그 문제가 없다.
        """
        row = await self._pool.fetchrow(
            """
            SELECT null_frac FROM pg_stats
            WHERE schemaname = $1 AND tablename = $2 AND attname = $3
            """,
            schema, table, column,
        )
        return row["null_frac"] if row else None

    async def last_analyzed(self, schema: str, table: str) -> float | None:
        row = await self._pool.fetchrow(
            """
            SELECT extract(epoch FROM last_analyze) AS ts
            FROM pg_stat_user_tables
            WHERE schemaname = $1 AND relname = $2
            """,
            schema,
            table,
        )
        return row["ts"] if row and row["ts"] is not None else None
