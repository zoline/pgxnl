"""어느 canonicalization 규칙이 실제로 편집을 냈는지 기록한다.

규칙을 뺄지 판단하려면 "등록돼 있었다"가 아니라 "일했다"를 세야 한다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import (
    DedupeColumnsRule, EnsureLimitRule, build_fallback_rule,
    canonicalize_sql, canonicalize_sql_verbose, load_rules_from_store,
)
from pgxnl.governance.rules import Rule
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _rule(rule_id: int, definition: dict, rule_type: str = "canonicalization") -> Rule:
    return Rule(id=rule_id, target_name="BIRD", rule_type=rule_type,
                definition=definition, enabled=True, updated_at=None)


_DUP = "SELECT COUNT(*) AS a, x, COUNT(*) AS b FROM t"


def test_편집을_낸_규칙만_보고한다(parser: AntlrPostgresParser) -> None:
    rules = [DedupeColumnsRule(), EnsureLimitRule(default_limit=100)]
    out, applied = canonicalize_sql_verbose(_DUP, parser, rules)
    assert "COUNT(*) AS b" in out and "LIMIT 100" in out
    assert applied == ["DedupeColumnsRule", "EnsureLimitRule"]


def test_아무도_편집을_안_내면_빈_목록(parser: AntlrPostgresParser) -> None:
    out, applied = canonicalize_sql_verbose("SELECT a FROM t LIMIT 10", parser, [DedupeColumnsRule()])
    assert out == "SELECT a FROM t LIMIT 10" and applied == []


def test_문법이_깨지면_손대지_않는다(parser: AntlrPostgresParser) -> None:
    bad = "SELECT FROM WHERE"
    out, applied = canonicalize_sql_verbose(bad, parser, [DedupeColumnsRule()])
    assert out == bad and applied == []


def test_라벨에_db_규칙_id가_붙는다() -> None:
    rules = load_rules_from_store([_rule(42, {"kind": "dedupe_columns"})])
    assert len(rules) == 1
    assert rules[0].source_rule_id == 42
    assert rules[0].label() == "DedupeColumnsRule(id 42)"


def test_id가_없으면_클래스_이름만() -> None:
    assert DedupeColumnsRule().label() == "DedupeColumnsRule"


def test_여러_규칙에_각자의_id가_붙는다() -> None:
    rules = load_rules_from_store([
        _rule(23, {"kind": "order_by_nulls", "mode": "sqlite"}),
        _rule(42, {"kind": "dedupe_columns"}),
    ])
    assert [r.source_rule_id for r in rules] == [23, 42]


def test_canonical_rewrite_규칙은_파서_단계에_실리지_않는다() -> None:
    # 재작성 규칙의 kind는 그 단계 안에서 폴백으로만 쓴다 — 파서 단계가 또 읽으면
    # 같은 변환이 두 번 돌고 어느 쪽이 일했는지 흐려진다.
    rules = load_rules_from_store([
        _rule(41, {"kind": "dedupe_columns", "bad_sql": "a", "good_sql": "b"}, "canonical_rewrite"),
    ])
    assert rules == []


def test_verbose가_아닌_판은_sql만_돌려준다(parser: AntlrPostgresParser) -> None:
    out = canonicalize_sql(_DUP, parser, [DedupeColumnsRule()])
    assert isinstance(out, str) and "COUNT(*) AS b" in out


@pytest.mark.parametrize("kind,expected", [
    ("dedupe_columns", "DedupeColumnsRule"),
    ("ensure_limit", "EnsureLimitRule"),
    ("order_by_nulls", None),   # 맥락 없이 만들 수는 있지만 폴백 대상은 아니다
    ("없는_이름", None),
])
def test_폴백_표(kind: str, expected: str | None) -> None:
    got = build_fallback_rule(kind)
    assert (type(got).__name__ if got else None) == expected
