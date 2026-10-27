"""AliasFixRule 테스트.

배경(run 103): 오답 18건 중 3건이 `column t1.street does not exist` 류였고, PostgreSQL이
HINT로 `t2.street`라고 정답까지 알려주고 있었다. california_schools는 테이블 간 이름이
겹치는 컬럼이 조인 키 `cdscode` 하나뿐이라 어느 테이블 것인지 모호함 없이 결정된다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import AliasFixRule, build_column_owners, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

OWNERS = {
    "street": {"schools"},
    "school": {"schools"},
    "charternum": {"schools"},
    "county": {"schools"},
    "school name": {"frpm"},
    "sname": {"satscores"},
    "cdscode": {"schools", "frpm"},  # 조인 키 — 양쪽에 있어 모호하다
}
JOINED = "FROM frpm T1 JOIN schools T2 ON T1.cdscode = T2.cdscode"


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def canon(parser, sql: str, owners=None) -> str:
    # 빈 dict도 유효한 입력이므로 `owners or OWNERS`로 쓰면 안 된다.
    return canonicalize_sql(sql, parser, [AliasFixRule(OWNERS if owners is None else owners)])


def test_wrong_alias_is_corrected(parser):
    assert canon(parser, f"SELECT T1.street {JOINED}") == f"SELECT t2.street {JOINED}"


def test_cte_alias_is_untouched(parser):
    """CTE 별칭은 카탈로그에 없어 '없는 컬럼'처럼 보인다 — 안쪽 테이블 별칭으로 바꾸면
    `missing FROM-clause entry` 로 죽는다(Northwind v2 run 565 seq 27)."""
    sql = ("WITH cr AS (SELECT T2.school, T2.street FROM schools T2) "
           "SELECT cr.school, cr.street FROM cr")
    assert canon(parser, sql) == sql


def test_correct_alias_is_untouched(parser):
    sql = f"SELECT T2.street {JOINED}"
    assert canon(parser, sql) == sql


def test_ambiguous_column_is_untouched(parser):
    """양쪽 테이블에 다 있는 컬럼은 고치면 안 된다 — 잘못 고치면 조용한 오답이 된다."""
    sql = f"SELECT T1.cdscode {JOINED}"
    assert canon(parser, sql) == sql


def test_multiple_references_corrected(parser):
    assert canon(parser, f"SELECT T1.school, T1.charternum {JOINED}") == (
        f"SELECT t2.school, t2.charternum {JOINED}"
    )


def test_owner_table_not_in_query_is_untouched(parser):
    """소유 테이블이 이 질의에 조인되지 않았으면 고칠 별칭이 없다."""
    sql = f"SELECT T1.sname {JOINED}"
    assert canon(parser, sql) == sql


def test_unknown_column_is_untouched(parser):
    """스키마에 없는 컬럼은 판단 근거가 없다."""
    sql = f"SELECT T1.nonexistent {JOINED}"
    assert canon(parser, sql) == sql


def test_quoted_column_name(parser):
    """공백 포함 컬럼명도 정규화해서 소유 테이블을 찾는다."""
    assert canon(parser, f'SELECT T2."School Name" {JOINED}') == f'SELECT t1."School Name" {JOINED}'


def test_where_clause_reference_corrected(parser):
    assert canon(parser, f"SELECT T1.cdscode {JOINED} WHERE T1.county = 'Monterey'") == (
        f"SELECT T1.cdscode {JOINED} WHERE t2.county = 'Monterey'"
    )


def test_single_table_query_is_untouched(parser):
    sql = "SELECT street FROM schools"
    assert canon(parser, sql) == sql


def test_non_select_is_untouched(parser):
    sql = "UPDATE schools SET street = 'x'"
    assert canon(parser, sql) == sql


def test_empty_owners_makes_rule_inert(parser):
    sql = f"SELECT T1.street {JOINED}"
    assert canon(parser, sql, owners={}) == sql


def test_build_column_owners_inverts_table_metadata():
    class Col:
        def __init__(self, name): self.name = name

    class Tbl:
        def __init__(self, name, cols): self.name, self.columns = name, [Col(c) for c in cols]

    owners = build_column_owners([Tbl("schools", ["CDSCode", "Street"]), Tbl("frpm", ["CDSCode", "School Name"])])
    assert owners["cdscode"] == {"schools", "frpm"}
    assert owners["street"] == {"schools"}
    assert owners["school name"] == {"frpm"}


def test_subquery_is_skipped_entirely(parser):
    """서브쿼리가 있으면 손대지 않는다.

    alias_to_table은 트리 전체에서 모은 것이라 스코프를 구분하지 못한다. 서브쿼리
    안에만 있는 별칭을 바깥 참조에 붙이면 `invalid reference to FROM-clause entry`로
    실행이 실패한다 — run 104 seq 447에서 실제로 발생했다.
    """
    sql = "SELECT T1.street FROM frpm T1 WHERE T1.cdscode IN (SELECT cdscode FROM schools)"
    assert canon(parser, sql) == sql


def test_subquery_with_own_alias_is_also_skipped(parser):
    sql = "SELECT T1.street FROM frpm T1 WHERE T1.cdscode IN (SELECT S.cdscode FROM schools S)"
    assert canon(parser, sql) == sql
