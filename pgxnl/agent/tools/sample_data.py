"""sample_data 도구. design 문서 §5.7 참고. 코드값·날짜 형식 파악용, 기본 50행."""
from __future__ import annotations

from pgxnl.connectors.postgresql import PgConnector


async def sample_data(conn: PgConnector, schema: str, table: str, *, row_limit: int = 50) -> list[dict]:
    sql = f'SELECT * FROM "{schema}"."{table}"'
    return await conn.execute_readonly(sql, row_limit=row_limit, timeout_seconds=10)
