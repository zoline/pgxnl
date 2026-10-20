"""같은 종류의 canonicalization 규칙이 대상 전용·전역에 겹칠 때(2026-10-02).

canonicalize_sql 은 한 번 파싱한 트리에 모든 규칙의 편집을 모아 적용하므로, 같은 종류가
둘이면 둘 다 편집을 내 SQL 이 깨진다(`DESC NULLS LAST NULLS LAST`). load_rules_from_store 가
종류마다 하나만 남긴다 — 대상 전용이 전역보다 우선.
"""
from datetime import datetime

import pytest

from pgxnl.agent.canonicalize import OrderByNullsRule, canonicalize_sql, load_rules_from_store
from pgxnl.governance.rules import Rule
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


def _r(id_, target, definition):
    return Rule(id=id_, target_name=target, rule_type="canonicalization", definition=definition,
                enabled=True, updated_at=datetime(2026, 10, 2))


@pytest.fixture(scope="module")
def parser():
    return AntlrPostgresParser()


def test_two_same_kind_rules_do_not_double_edit(parser):
    # 예전엔 같은 종류 규칙 둘이 같은 편집을 내 "NULLS LAST NULLS LAST" 가 됐다(로딩 단계 _one_per_kind 가
    # 막았다). 2026-10-14 부터는 canonicalize_sql_verbose 가 같은 편집을 한 번만 적용해 이 단계에서도 막힌다.
    out = canonicalize_sql("SELECT a FROM t ORDER BY a DESC", parser,
                           [OrderByNullsRule("sqlite"), OrderByNullsRule("desc_last")])
    assert "NULLS LAST NULLS LAST" not in out and out.count("NULLS LAST") == 1


def test_target_rule_wins_over_global_and_keeps_bird_output(parser):
    sqlite_bird = _r(23, "BIRD", {"kind": "order_by_nulls", "mode": "sqlite"})
    global_desc = _r(42, None, {"kind": "order_by_nulls", "mode": "desc_last"})
    rules = load_rules_from_store([sqlite_bird, global_desc])
    assert [r.source_rule_id for r in rules] == [23]
    sql = "SELECT a, b FROM t ORDER BY a ASC, b DESC LIMIT 5"
    assert canonicalize_sql(sql, parser, rules) == canonicalize_sql(sql, parser, [OrderByNullsRule("sqlite")])


def test_target_rule_wins_even_when_global_has_smaller_id():
    global_desc = _r(5, None, {"kind": "order_by_nulls", "mode": "desc_last"})
    sqlite_bird = _r(23, "BIRD", {"kind": "order_by_nulls", "mode": "sqlite"})
    rules = load_rules_from_store([global_desc, sqlite_bird])
    assert [r.source_rule_id for r in rules] == [23]


def test_global_only_applies_desc_last(parser):
    rules = load_rules_from_store([_r(42, None, {"kind": "order_by_nulls", "mode": "desc_last"})])
    out = canonicalize_sql("SELECT a, b FROM t ORDER BY a, b DESC", parser, rules)
    assert "NULLS FIRST" not in out.upper() and out.upper().count("NULLS LAST") == 1


def test_different_kinds_all_kept_in_id_order():
    rules = load_rules_from_store([
        _r(1, None, {"kind": "dedupe_columns"}),
        _r(2, "BIRD", {"kind": "order_by_nulls", "mode": "sqlite"}),
        _r(3, None, {"kind": "ensure_limit", "default_limit": 10}),
    ])
    assert [r.source_rule_id for r in rules] == [1, 2, 3]


def _rs(id_, target, schema, definition):
    return Rule(id=id_, target_name=target, rule_type="canonicalization", definition=definition,
                enabled=True, updated_at=datetime(2026, 10, 6), schema_name=schema)


def test_schema_rule_wins_over_target_and_global():
    """스키마 전용 > 대상 전용 > 전역 (2026-10-06)."""
    rules = load_rules_from_store([
        _rs(5, None, None, {"kind": "order_by_nulls", "mode": "desc_last"}),
        _rs(23, "BIRD", None, {"kind": "order_by_nulls", "mode": "sqlite"}),
        _rs(50, "BIRD", "card_games", {"kind": "order_by_nulls", "mode": "nulls_last"}),
    ])
    assert [r.source_rule_id for r in rules] == [50]
