"""테이블 하나뿐인 조회에서 별칭을 뗀다 (2026-10-07)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import AliasFixRule, SingleTableNoAliasRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _canon(parser, sql: str) -> str:
    return canonicalize_sql(sql, parser, [SingleTableNoAliasRule()])


@pytest.mark.parametrize("sql,expected", [
    ("SELECT T1.name FROM sets AS T1 WHERE T1.code = 'KLD'",
     "SELECT name FROM sets WHERE code = 'KLD'"),
    ("SELECT COUNT(T1.id) FROM cards AS T1 WHERE T1.power IS NULL ORDER BY T1.name LIMIT 1",
     "SELECT COUNT(id) FROM cards WHERE power IS NULL ORDER BY name LIMIT 1"),
    ('SELECT t1."School Name" FROM frpm t1 WHERE t1."Free Meal Count (K-12)" > 1',
     'SELECT "School Name" FROM frpm WHERE "Free Meal Count (K-12)" > 1'),
    ("SELECT DISTINCT T1.name FROM sets AS T1", "SELECT DISTINCT name FROM sets"),
    ("SELECT T1.* FROM sets AS T1", "SELECT * FROM sets"),
    ("SELECT CASE WHEN T1.x IS NOT NULL THEN 'YES' ELSE 'NO' END FROM t AS T1 GROUP BY T1.x",
     "SELECT CASE WHEN x IS NOT NULL THEN 'YES' ELSE 'NO' END FROM t GROUP BY x"),
])
def test_별칭을_뗀다(parser, sql: str, expected: str) -> None:
    assert _canon(parser, sql) == expected


@pytest.mark.parametrize("sql", [
    "SELECT T1.name FROM cards AS T1 INNER JOIN sets AS T2 ON T1.setcode = T2.code",   # 조인
    "SELECT T1.a FROM t AS T1, u AS T2 WHERE T1.id = T2.id",                            # 쉼표 조인
    "SELECT T1.a FROM t AS T1 WHERE T1.b = (SELECT MAX(T2.b) FROM t AS T2)",            # 서브쿼리
    "SELECT T1.a FROM t AS T1 WHERE EXISTS (SELECT 1 FROM t AS T2 WHERE T2.p = T1.a)",  # 상관 서브쿼리
    "WITH x AS (SELECT a FROM t) SELECT x.a FROM x",                                     # CTE
    "SELECT name FROM sets WHERE code = 'KLD'",                                          # 별칭 없음
    "SELECT sets.name FROM sets",                                                        # 테이블명 한정은 그대로
    "SELECT T1.a FROM t AS T1 UNION SELECT T1.a FROM u AS T1",                           # UNION
])
def test_건드리지_않는다(parser, sql: str) -> None:
    assert _canon(parser, sql) == sql


def test_alias_fix와_함께_돌려도_깨지지_않는다(parser) -> None:
    sql = "SELECT T1.name FROM sets AS T1 WHERE T1.code = 'KLD'"
    out = canonicalize_sql(sql, parser, [AliasFixRule({"name": {"sets"}, "code": {"sets"}}), SingleTableNoAliasRule()])
    assert out == "SELECT name FROM sets WHERE code = 'KLD'"
