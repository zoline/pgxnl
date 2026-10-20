"""YEAR()/MONTH()/DAY() → EXTRACT (BIRD codebase_community 330·336, 2026-10-14)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import DatePartFuncRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _canon(parser, sql):
    return canonicalize_sql(sql, parser, [DatePartFuncRule()])


def test_bird_336_실제_sql(parser):
    sql = ("SELECT CAST(COUNT(CASE WHEN YEAR(T2.creationdate) = 2011 AND T2.reputation > 1000 THEN T1.id END) AS REAL) "
           "* 100 / NULLIF(COUNT(T1.id), 0) FROM posts AS T1 INNER JOIN users AS T2 ON T1.owneruserid = T2.id")
    out = _canon(parser, sql)
    assert "EXTRACT(YEAR FROM T2.creationdate) = 2011" in out and "YEAR(" not in out.replace("EXTRACT(YEAR", "")


def test_bird_330_where(parser):
    sql = "SELECT COUNT(T1.id) FROM postlinks AS T1 WHERE YEAR(T1.creationdate) = 2010"
    assert _canon(parser, sql) == "SELECT COUNT(T1.id) FROM postlinks AS T1 WHERE EXTRACT(YEAR FROM T1.creationdate) = 2010"


@pytest.mark.parametrize("fn,part", [("month", "MONTH"), ("Day", "DAY"), ("year", "YEAR")])
def test_대소문자_무관(parser, fn, part):
    assert _canon(parser, f"SELECT {fn}(d) FROM t") == f"SELECT EXTRACT({part} FROM d) FROM t"


def test_중첩_인자(parser):
    out = _canon(parser, "SELECT YEAR(CAST(d AS TIMESTAMP)) FROM t")
    assert out == "SELECT EXTRACT(YEAR FROM CAST(d AS TIMESTAMP)) FROM t"


@pytest.mark.parametrize("sql", [
    "SELECT EXTRACT(YEAR FROM d) FROM t",
    "SELECT year FROM t",                       # 컬럼 이름
    "SELECT myschema.year(d) FROM t",           # 스키마 한정 — 사용자 함수일 수 있다
    "SELECT year(a, b) FROM t",                 # 인자 둘
    "SELECT TO_CHAR(d, 'YYYY') FROM t",
])
def test_그대로(parser, sql):
    assert _canon(parser, sql) == sql
