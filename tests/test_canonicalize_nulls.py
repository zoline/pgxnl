"""OrderByNullsRule 테스트.

배경: PostgreSQL 기본은 ASC->NULLS LAST / DESC->NULLS FIRST인데 SQLite는 정확히
반대다. BIRD gold는 SQLite 정렬을 명시적 NULLS 절로 보존했고, 모델은 그걸 몰라
`DESC`만 써서 NULL 행이 1위로 올라오는 오답을 낸다(실측 오답의 47%).
"""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import OrderByNullsRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def canon(parser, sql: str, mode: str = "desc_last") -> str:
    return canonicalize_sql(sql, parser, [OrderByNullsRule(mode=mode)])


def test_desc_gets_nulls_last(parser):
    assert canon(parser, "SELECT a FROM t ORDER BY x DESC LIMIT 1") == (
        "SELECT a FROM t ORDER BY x DESC NULLS LAST LIMIT 1"
    )


def test_desc_last_mode_leaves_asc_alone(parser):
    """기본 모드는 ASC를 건드리지 않는다 — ASC의 NULL 위치는 PostgreSQL 기본으로
    두는 것이 실제 업무 DB에서 안전하다."""
    sql = "SELECT a FROM t ORDER BY x ASC LIMIT 1"
    assert canon(parser, sql) == sql


def test_sqlite_mode_also_fixes_asc(parser):
    assert canon(parser, "SELECT a FROM t ORDER BY x ASC", mode="sqlite") == (
        "SELECT a FROM t ORDER BY x ASC NULLS FIRST"
    )


def test_bare_order_by_is_asc_in_sqlite_mode(parser):
    """ASC/DESC 표기가 없으면 ASC로 본다(PostgreSQL 기본)."""
    assert canon(parser, "SELECT a FROM t ORDER BY x", mode="sqlite") == (
        "SELECT a FROM t ORDER BY x NULLS FIRST"
    )


def test_existing_nulls_clause_is_untouched(parser):
    """이미 명시된 NULL 정렬을 덮어쓰면 모델이 의도한 의미를 파괴한다."""
    sql = "SELECT a FROM t ORDER BY x DESC NULLS FIRST LIMIT 1"
    assert canon(parser, sql) == sql


def test_multiple_sort_keys(parser):
    assert canon(parser, "SELECT a FROM t ORDER BY b DESC, c ASC") == (
        "SELECT a FROM t ORDER BY b DESC NULLS LAST, c ASC"
    )


def test_no_order_by_is_unchanged(parser):
    sql = "SELECT a FROM t"
    assert canon(parser, sql) == sql


def test_non_select_is_unchanged(parser):
    sql = "UPDATE t SET a = 1"
    assert canon(parser, sql) == sql


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        OrderByNullsRule(mode="nonsense")


def test_malformed_definition_does_not_break_loading():
    """규칙 정의가 dict가 아니어도(jsonb 이중 인코딩 등) 전체 로딩이 죽으면 안 된다.

    실측 사고: definition이 str로 읽히면서 `.get()`이 터졌고, 그 예외가 그대로 올라가
    BIRD 30문항이 전부 실패했다(run 102). 보조 기능 실패가 필수 경로를 막은 사례.
    """
    from pgxnl.agent.canonicalize import load_rules_from_store
    from pgxnl.governance.rules import Rule

    broken = Rule(id=1, target_name=None, rule_type="canonicalization",
                  definition='{"kind": "order_by_nulls"}', enabled=True, updated_at=None)
    good = Rule(id=2, target_name=None, rule_type="canonicalization",
                definition={"kind": "order_by_nulls", "mode": "desc_last"}, enabled=True, updated_at=None)

    rules = load_rules_from_store([broken, good])
    assert len(rules) == 1
    assert isinstance(rules[0], OrderByNullsRule)


def test_nulls_last_mode_marks_both_directions(parser):
    """기본 모드는 ASC/DESC 모두 NULLS LAST를 명시한다.

    ASC는 PostgreSQL 기본이 이미 NULLS LAST라 결과가 바뀌지 않지만, 명시해두면 의도가
    SQL에 드러나고 기본값이 다른 DB로 옮겨도 같은 의미를 유지한다.
    """
    assert canon(parser, "SELECT a FROM t ORDER BY b DESC, c ASC", mode="nulls_last") == (
        "SELECT a FROM t ORDER BY b DESC NULLS LAST, c ASC NULLS LAST"
    )


def test_nulls_last_is_the_default(parser):
    assert canonicalize_sql("SELECT a FROM t ORDER BY x ASC", parser, [OrderByNullsRule()]) == (
        "SELECT a FROM t ORDER BY x ASC NULLS LAST"
    )


def test_bare_order_by_gets_nulls_last(parser):
    """ASC/DESC 표기가 없으면 ASC로 본다(PostgreSQL 기본)."""
    assert canon(parser, "SELECT a FROM t ORDER BY x", mode="nulls_last") == (
        "SELECT a FROM t ORDER BY x NULLS LAST"
    )


def test_nulls_last_does_not_override_explicit_clause(parser):
    sql = "SELECT a FROM t ORDER BY x ASC NULLS FIRST"
    assert canon(parser, sql, mode="nulls_last") == sql
