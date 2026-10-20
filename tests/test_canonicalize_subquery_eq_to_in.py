"""조건의 `= (SELECT …)` 를 `IN (SELECT …)` 로 (BIRD card_games seq 379, 2026-10-14)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import SubqueryEqToInRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _canon(parser: AntlrPostgresParser, sql: str) -> str:
    return canonicalize_sql(sql, parser, [SubqueryEqToInRule()])


def test_bird_379_실제_sql(parser: AntlrPostgresParser) -> None:
    sql = ("SELECT CASE WHEN EXISTS (SELECT 1 FROM set_translations AS T1 "
           "WHERE T1.setcode = (SELECT T2.setcode FROM cards AS T2 WHERE T2.name = 'Ancestor''s Chosen') "
           "AND T1.language = 'Korean') THEN 'YES' ELSE 'NO' END")
    out = _canon(parser, sql)
    assert "T1.setcode IN (SELECT T2.setcode" in out
    assert "T2.name = 'Ancestor''s Chosen'" in out  # 안쪽의 값 비교는 그대로


@pytest.mark.parametrize("sql", [
    "SELECT a FROM t WHERE x = (SELECT y FROM u)",
    "SELECT a FROM t WHERE b = 1 AND (c = 2 OR x = (SELECT y FROM u))",
    "SELECT a FROM t JOIN u ON t.k = (SELECT k FROM v)",
    "SELECT a FROM t GROUP BY a HAVING COUNT(*) = (SELECT n FROM u WHERE k = 1)",
    "SELECT a FROM t WHERE x = (SELECT y FROM u WHERE y IN (SELECT MAX(z) FROM v))",  # 집계가 더 안쪽
    "SELECT CASE WHEN x = (SELECT y FROM u) THEN 1 ELSE 0 END FROM t",
])
def test_조건_위치는_바꾼다(parser: AntlrPostgresParser, sql: str) -> None:
    out = _canon(parser, sql)
    assert "IN (SELECT" in out and "= (SELECT" not in out


@pytest.mark.parametrize("sql", [
    "SELECT a FROM t WHERE NOT x = (SELECT y FROM u)",           # 0행이면 NULL 대 true 로 갈린다
    "SELECT a FROM t WHERE NOT (x = (SELECT y FROM u))",
    "SELECT a FROM t WHERE (x = (SELECT y FROM u)) IS NOT TRUE",
    "SELECT x = (SELECT y FROM u) FROM t",                        # SELECT 목록의 비교 결과
    "SELECT a FROM t WHERE x <> (SELECT y FROM u)",               # 다른 연산자
    "SELECT a FROM t WHERE x < (SELECT y FROM u)",
    "SELECT a FROM t WHERE x = (SELECT y FROM u) + 1",            # 서브쿼리 자체가 아니다
    "SELECT a FROM t WHERE (SELECT y FROM u) = x",                # 왼쪽 서브쿼리
    "SELECT a FROM t WHERE x = 1",
    "SELECT CASE WHEN a THEN x = (SELECT y FROM u) END FROM t",   # THEN 결과
])
def test_그대로_두는_경우(parser: AntlrPostgresParser, sql: str) -> None:
    assert _canon(parser, sql) == sql


@pytest.mark.parametrize("sql", [
    # 390: GROUP BY 없는 집계 — 늘 한 행
    "SELECT name FROM cards WHERE cmc = (SELECT MAX(T2b.cmc) FROM cards AS T2b WHERE T2b.setcode = 'CSP')",
    # 393: LIMIT 1
    "SELECT T1.format FROM legalities AS T1 WHERE T1.status = 'Banned' AND T1.format = "
    "(SELECT T3.format FROM legalities AS T3 GROUP BY T3.format ORDER BY COUNT(*) DESC LIMIT 1)",
    "SELECT a FROM t WHERE x = (SELECT y FROM u FETCH FIRST 1 ROW ONLY)",
    "SELECT a FROM t WHERE x = (SELECT COUNT(*) FROM u)",
    "SELECT a FROM t WHERE x = (SELECT MAX(y) FROM u GROUP BY g)",
    "SELECT a FROM t WHERE x = (SELECT y FROM u ORDER BY y LIMIT 2)",
])
def test_LIMIT_집계가_있으면_그대로(parser: AntlrPostgresParser, sql: str) -> None:
    assert _canon(parser, sql) == sql
