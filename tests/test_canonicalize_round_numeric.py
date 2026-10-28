"""ROUND(식, n) → ROUND((식)::numeric, n) (Northwind L4-04, 2026-10-28)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import RoundNumericRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _canon(parser, sql):
    return canonicalize_sql(sql, parser, [RoundNumericRule()])


def test_northwind_l4_04_cast_then_double(parser):
    """캐스트 뒤에 double 과 다시 연산하면 결과가 double 이 된다 — 바깥을 감싼다."""
    sql = "SELECT ROUND(CAST(cr.revenue AS NUMERIC) / tr.total * 100, 2) AS pct FROM cr, tr"
    assert _canon(parser, sql) == "SELECT ROUND((CAST(cr.revenue AS NUMERIC) / tr.total * 100)::numeric, 2) AS pct FROM cr, tr"


def test_plain_expression_is_wrapped(parser):
    assert _canon(parser, "SELECT ROUND(AVG(o.freight), 2) FROM orders o") == \
        "SELECT ROUND((AVG(o.freight))::numeric, 2) FROM orders o"


def test_already_numeric_is_untouched(parser):
    for sql in ("SELECT ROUND(CAST(SUM(x) AS NUMERIC), 2) FROM t",
                "SELECT ROUND(SUM(x)::numeric, 2) FROM t",
                "SELECT ROUND(CAST(x AS numeric(10,2)), 1) FROM t"):
        assert _canon(parser, sql) == sql


def test_single_argument_round_is_untouched(parser):
    """ROUND(double) 한 인자는 PostgreSQL 에 있다."""
    sql = "SELECT ROUND(AVG(x)) FROM t"
    assert _canon(parser, sql) == sql


def test_nested_round_in_cte(parser):
    sql = "WITH m AS (SELECT SUM(x) AS s FROM t) SELECT ROUND(100 * s / LAG(s) OVER (ORDER BY s), 2) FROM m"
    assert _canon(parser, sql) == ("WITH m AS (SELECT SUM(x) AS s FROM t) "
                                   "SELECT ROUND((100 * s / LAG(s) OVER (ORDER BY s))::numeric, 2) FROM m")
