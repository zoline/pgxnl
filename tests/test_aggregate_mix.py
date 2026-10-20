"""GROUP BY 없이 집계와 비집계 컬럼을 섞은 SELECT 를 잡는다 (BIRD card_games seq 353)."""
from __future__ import annotations

import pytest

from pgxnl.agent.aggregate_mix import find_aggregate_mix
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _find(parser: AntlrPostgresParser, sql: str):
    return find_aggregate_mix(parser.parse(sql))


BIRD_353 = (
    "SELECT CAST(CASE WHEN T1.language = 'Chinese Simplified' THEN 1 ELSE 0 END AS REAL) * 100 "
    "/ NULLIF(COUNT(T1.id), 0) AS percentage FROM foreign_data AS T1"
)


def test_bird_353_실제_실패_sql을_잡는다(parser: AntlrPostgresParser) -> None:
    found = _find(parser, BIRD_353)
    assert len(found) == 1
    assert found[0].column == "T1.language"
    assert found[0].aggregate.upper() == "COUNT"


def test_메시지가_실제_오류문구와_고칠_방법을_담는다(parser: AntlrPostgresParser) -> None:
    msg = _find(parser, BIRD_353)[0].message()
    assert "must appear in the GROUP BY clause" in msg
    assert "SUM(CASE WHEN" in msg


@pytest.mark.parametrize("sql", [
    "SELECT name, COUNT(*) FROM t",
    "SELECT * FROM (SELECT a, MAX(b) FROM t) AS x",   # 서브쿼리 안쪽도 따로 본다
])
def test_혼용을_잡는다(parser: AntlrPostgresParser, sql: str) -> None:
    assert _find(parser, sql)


@pytest.mark.parametrize("sql", [
    "SELECT CAST(SUM(CASE WHEN T1.language = 'x' THEN 1 ELSE 0 END) AS REAL) * 100 / NULLIF(COUNT(T1.id), 0) FROM foreign_data AS T1",
    "SELECT CAST(COUNT(CASE WHEN T1.language = 'x' THEN T1.id END) AS REAL) * 100 / NULLIF(COUNT(T1.id), 0) FROM foreign_data AS T1",
    "SELECT a, COUNT(*) FROM t GROUP BY a",            # GROUP BY 가 있으면 보지 않는다
    "SELECT a, RANK() OVER (ORDER BY b) FROM t",        # 윈도 함수는 집계가 아니다
    "SELECT a, SUM(b) OVER () FROM t",
    "SELECT a FROM t WHERE b = (SELECT MAX(b) FROM t)",
    "SELECT a, (SELECT COUNT(*) FROM u WHERE u.x = t.a) FROM t",  # 스칼라 서브쿼리 안의 집계
    "SELECT COUNT(*) FILTER (WHERE a > 1) FROM t",
    "SELECT COUNT(*) FROM a UNION SELECT COUNT(*) FROM b",
    "SELECT a, b FROM t",
])
def test_정상_sql은_건드리지_않는다(parser: AntlrPostgresParser, sql: str) -> None:
    assert _find(parser, sql) == []
