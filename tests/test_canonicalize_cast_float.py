"""지정 컬럼의 REAL 캐스트를 FLOAT 로 (debit_card 3·13, 2026-10-19)."""
import pytest

from pgxnl.agent.canonicalize import CastFloatRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser():
    return AntlrPostgresParser()


def _c(parser, sql):
    return canonicalize_sql(sql, parser, [CastFloatRule(["consumption"])])


def test_cast_function(parser):
    assert _c(parser, "SELECT SUM(CAST(T1.consumption AS REAL)) FROM yearmonth T1") == \
        "SELECT SUM(CAST(T1.consumption AS FLOAT)) FROM yearmonth T1"


def test_cast_around_aggregate_and_typecast(parser):
    out = _c(parser, "SELECT CAST(SUM(consumption) AS REAL) / 2, consumption::real FROM yearmonth")
    assert "CAST(SUM(consumption) AS FLOAT)" in out and "consumption::FLOAT" in out


@pytest.mark.parametrize("sql", [
    "SELECT CAST(price AS REAL) FROM t",                       # 다른 컬럼
    "SELECT CAST(consumption AS FLOAT) FROM t",                # 이미 FLOAT
    "SELECT CAST(consumptions AS REAL) FROM t",                # 이름이 다르다
])
def test_untouched(parser, sql):
    assert _c(parser, sql) == sql
