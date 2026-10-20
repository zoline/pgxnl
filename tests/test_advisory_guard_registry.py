"""조언형 가드 분류 통합 — `advisory_guard` 와 구 분류를 함께 읽는다.

`stats_guard`(근거=컬럼 통계)와 `question_guard`(근거=질문 텍스트)를 가르던 축은
사용자에게 의미가 없었다 — 하는 일이 "루프에 조언을 돌려준다"로 같다. 정작 중요한
축은 **고칠 때까지 되돌리는가 vs 한 번만 알리는가**인데 그 분류로는 표현되지 않았다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.stats_guard import DEFAULT_THRESHOLD, parse_rule
from pgxnl.governance.rules import LEGACY_GUARD_TYPES, RuleType


def test_구_분류_이름이_보존된다() -> None:
    # 이행 전 데이터를 읽어야 하므로 이 둘이 사라지면 기존 규칙이 조용히 죽는다.
    assert LEGACY_GUARD_TYPES == ("stats_guard", "question_guard")


def test_advisory_guard가_유효한_rule_type이다() -> None:
    assert "advisory_guard" in RuleType.__args__
    # 구 이름도 여전히 유효해야 한다 — 이행 중 양쪽이 동작한다.
    for legacy in LEGACY_GUARD_TYPES:
        assert legacy in RuleType.__args__


@pytest.mark.parametrize("definition", [
    {"kind": "ambiguous_column", "min_length": 4},
    {"kind": "column_rationale"},
    {"kind": "redundant_join"},
    {"kind": "single_column", "strict": True},
    {"kind": "dedupe_columns"},
    {},
])
def test_trigger가_없는_정의는_null비율_가드로_읽히지_않는다(definition: dict) -> None:
    """한 통에 여러 kind가 섞여도 null비율 가드는 자기 것만 집는다.

    분류를 합치면 이 경로가 다른 kind의 정의까지 받는다 — `trigger` 없는 정의가
    조용히 "모든 낱말에 발동"으로 해석되면 30문항 전부에 잘못된 조언이 나간다.
    """
    assert parse_rule(definition) is None


def test_trigger가_있으면_임계값과_함께_읽는다() -> None:
    assert parse_rule({"trigger": ["valid"], "threshold": 0.99}) == (["valid"], 0.99)


def test_trigger가_문자열_하나여도_읽는다() -> None:
    assert parse_rule({"trigger": "valid"}) == (["valid"], DEFAULT_THRESHOLD)


def test_임계값이_숫자가_아니면_기본값을_쓴다() -> None:
    assert parse_rule({"trigger": ["valid"], "threshold": "이상한값"}) == (["valid"], DEFAULT_THRESHOLD)


# ---- 2026-09-14 이행 후: 실제 등록된 kind 들이 모두 자기 경로로 간다 ----

_MIGRATED = [
    {"kind": "null_ratio", "trigger": ["valid"], "threshold": 0.99},
    {"kind": "single_column", "strict": True},
    {"kind": "ambiguous_column", "min_length": 4},
    {"kind": "column_rationale"},
    {"kind": "redundant_join"},
]


def test_이행된_정의_중_null비율만_그_가드로_읽힌다() -> None:
    """한 통에 다섯 kind가 섞여 있다 — null비율 경로가 자기 것만 집어야 한다."""
    parsed = [d for d in _MIGRATED if parse_rule(d) is not None]
    assert [d["kind"] for d in parsed] == ["null_ratio"]


def test_kind가_없는_구_정의도_여전히_읽힌다() -> None:
    """이행 전 29번은 `{"trigger": [...], "threshold": ...}` 였다. 다른 대상 DB에
    그런 행이 남아 있어도 동작해야 한다."""
    assert parse_rule({"trigger": ["valid"], "threshold": 0.99}) == (["valid"], 0.99)
