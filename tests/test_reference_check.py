"""대조 gold 기반 "원본 gold 결함 후보" 판정 테스트.

DB 없이 돌도록 execute를 주입한다 — 판정 로직 자체가 검증 대상이고, 실제 실행은
호출자(운영 코드)의 책임이다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from pgxnl.agent.evaluation import reference_check as R


@dataclass
class Item:
    seq: int
    question_id: str
    gold_sql: str
    pred_sql: str | None
    ex_pass: bool | None


def executor(results: dict[str, list[dict]]):
    """SQL 문자열 -> 결과 행. 등록되지 않은 SQL은 예외를 던져 실행 실패를 흉내낸다."""

    async def execute(sql: str):
        if sql not in results:
            raise ValueError(f"실행 실패: {sql}")
        return results[sql]

    return execute


@pytest.mark.asyncio
async def test_pred_matching_reference_is_a_defect_candidate():
    """pred가 대조 gold와 같고 원본 gold와 다르면 원본이 의심스럽다."""
    items = [Item(445, "26", "GOLD", "PRED", False)]
    execute = executor({"GOLD": [{"a": 1}], "PRED": [{"a": 1}, {"a": 2}], "REF": [{"a": 1}, {"a": 2}]})
    found = await R.check_run(items, {"26": "REF"}, execute)
    assert [f.verdict for f in found] == [R.GOLD_DEFECT_CANDIDATE]


@pytest.mark.asyncio
async def test_pred_differing_from_reference_is_pred_wrong():
    items = [Item(1, "10", "GOLD", "PRED", False)]
    execute = executor({"GOLD": [{"a": 1}], "PRED": [{"a": 9}], "REF": [{"a": 1}, {"a": 2}]})
    found = await R.check_run(items, {"10": "REF"}, execute)
    assert found[0].verdict == R.PRED_WRONG


@pytest.mark.asyncio
async def test_reference_equal_to_gold_is_undecidable():
    """대조 gold가 원본과 같은 결과면 판정에 쓸 수 없다 — 오답 원인을 가려주지 못한다."""
    items = [Item(1, "10", "GOLD", "PRED", False)]
    execute = executor({"GOLD": [{"a": 1}], "PRED": [{"a": 9}], "REF": [{"a": 1}]})
    found = await R.check_run(items, {"10": "REF"}, execute)
    assert found[0].verdict == R.REFERENCE_SAME


@pytest.mark.asyncio
async def test_passing_items_are_skipped():
    """정답 문항은 대조할 이유가 없다 — 대상 DB에 불필요한 쿼리를 던지지 않는다."""
    items = [Item(1, "10", "GOLD", "PRED", True)]
    execute = executor({})
    assert await R.check_run(items, {"10": "REF"}, execute) == []


@pytest.mark.asyncio
async def test_missing_reference_or_pred_is_skipped():
    execute = executor({})
    assert await R.check_run([Item(1, "10", "G", "P", False)], {}, execute) == []
    assert await R.check_run([Item(1, "10", "G", None, False)], {"10": "REF"}, execute) == []
    assert await R.check_run([Item(1, "10", "G", "   ", False)], {"10": "REF"}, execute) == []


@pytest.mark.asyncio
async def test_execution_failure_is_reported_not_raised():
    """대조 gold가 안 돌아도 전체 진단이 죽으면 안 된다."""
    items = [Item(1, "10", "GOLD", "PRED", False)]
    execute = executor({"GOLD": [], "PRED": []})  # REF 없음 -> 예외
    found = await R.check_run(items, {"10": "REF"}, execute)
    assert found[0].verdict == R.ERROR
    assert "실행 실패" in found[0].detail


def test_render_lists_candidates():
    findings = [
        R.ReferenceFinding(445, "26", R.GOLD_DEFECT_CANDIDATE, "pred가 대조 gold와 일치"),
        R.ReferenceFinding(1, "10", R.PRED_WRONG, "대조 gold와도 다름"),
    ]
    text = R.render(findings)
    assert "GOLD_DEFECT_CANDIDATE" in text
    assert "seq 445" in text


def test_load_reference_accepts_both_key_names(tmp_path):
    import json

    p = tmp_path / "ref.json"
    p.write_text(json.dumps([{"question_id": 1, "SQL": "A"}, {"question_id": "2", "gold_sql": "B"}]))
    assert R.load_reference(str(p)) == {"1": "A", "2": "B"}
