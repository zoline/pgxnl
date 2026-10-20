"""timestamp 컬럼 vs 날짜 리터럴 → DATE(컬럼) (BIRD codebase_community 299, 2026-10-14)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import DateLiteralCompareRule, canonicalize_sql, load_rules_from_store
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

TS = {"users": {"lastaccessdate", "creationdate"}, "posts": {"creaiondate"}, "votes": set()}


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _canon(parser, sql):
    return canonicalize_sql(sql, parser, [DateLiteralCompareRule(TS)])


def test_bird_299(parser):
    assert _canon(parser, "SELECT COUNT(*) FROM users WHERE lastaccessdate > '2014-09-01'") == \
        "SELECT COUNT(*) FROM users WHERE DATE(lastaccessdate) > '2014-09-01'"


def test_별칭_조인(parser):
    sql = ("SELECT COUNT(*) FROM posts AS T1 INNER JOIN users AS T2 ON T1.owneruserid = T2.id "
           "WHERE T2.creationdate = '2011/1/5' AND T1.creaiondate BETWEEN '2010-01-01' AND '2010-12-31'")
    out = _canon(parser, sql)
    assert "DATE(T2.creationdate) = '2011/1/5'" in out
    assert "DATE(T1.creaiondate) BETWEEN '2010-01-01' AND '2010-12-31'" in out


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM users WHERE lastaccessdate > '2014-09-01 12:00:00'",   # 시각이 붙은 리터럴
    "SELECT 1 FROM users WHERE DATE(lastaccessdate) > '2014-09-01'",     # 이미 함수
    "SELECT 1 FROM votes WHERE creationdate = '2010-07-19'",             # date 컬럼(timestamp 아님)
    "SELECT 1 FROM users WHERE displayname = '2014-09-01'",              # timestamp 아닌 컬럼
    "SELECT 1 FROM users AS T1 WHERE T1.lastaccessdate > T1.creationdate",
    "SELECT 1 FROM users WHERE lastaccessdate > '2014-09-01'::date + 1",
])
def test_그대로(parser, sql):
    assert _canon(parser, sql) == sql


def test_컬럼_정보_없으면_규칙을_만들지_않는다():
    from datetime import datetime

    from pgxnl.governance.rules import Rule
    r = Rule(id=51, target_name="BIRD", rule_type="canonicalization", definition={"kind": "date_literal_compare"},
             enabled=True, updated_at=datetime(2026, 10, 14))
    assert load_rules_from_store([r]) == []
    assert len(load_rules_from_store([r], timestamp_columns=TS)) == 1
