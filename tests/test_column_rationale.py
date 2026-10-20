"""SELECT 항목 ↔ 질문 구절 대응 가드 (`agent/column_rationale.py`).

기존 `single_column` 가드(규칙 30)는 개수만 봐서 어느 컬럼이 군더더기인지 못 짚었고,
정밀도 97.9%에도 EX 기여가 0이었다. 여기서는 항목을 지목한다 — 모델이 무엇을 지울지
알 수 있어야 조언이 실행 가능하다.
"""
from __future__ import annotations

from pgxnl.agent.column_rationale import find_unsupported, parse_rationale

Q = ("What is the eligible free rate of the 10th and 11th schools with the highest "
     "enrolment for students in grades 1 through 12?")


def test_none_quote_is_flagged():
    """BIRD 448: 모델이 요구하지 않은 School Name을 SELECT에 넣었다."""
    rows = parse_rationale(
        'T1."School Name" | NONE | CONDITION\n'
        "CAST(...) AS rate | eligible free rate | REQUESTED", Q)
    out = find_unsupported(rows, select_count=2)
    assert out is not None
    assert out.items == ('T1."School Name"',)
    assert '"School Name"' in out.message()


def test_fabricated_quote_is_flagged():
    """인용이 질문 원문에 없으면 근거를 지어낸 것이다 — 믿을 수 없으므로 지적한다."""
    rows = parse_rationale(
        "T1.district | the district of the school | REQUESTED\n"
        "CAST(...) AS rate | eligible free rate | REQUESTED", Q)
    assert find_unsupported(rows, select_count=2).items == ("T1.district",)


def test_condition_only_column_is_flagged():
    """질문이 조건으로만 언급한 값은 결과에 넣을 이유가 없다."""
    rows = parse_rationale(
        "T1.enrolment | highest enrolment | CONDITION\n"
        "CAST(...) AS rate | eligible free rate | REQUESTED", Q)
    assert find_unsupported(rows, select_count=2).items == ("T1.enrolment",)


def test_all_requested_is_not_flagged():
    rows = parse_rationale(
        "T1.school | schools | REQUESTED\n"
        "CAST(...) AS rate | eligible free rate | REQUESTED", Q)
    assert find_unsupported(rows, select_count=2) is None


def test_row_count_mismatch_gives_up():
    """모델이 항목 수를 못 맞추면 어느 항목을 말하는지 신뢰할 수 없다."""
    rows = parse_rationale('T1."School Name" | NONE | CONDITION', Q)
    assert find_unsupported(rows, select_count=3) is None


def test_all_flagged_gives_up():
    """전부 근거 없다고 나오면 SQL을 통째로 부정하는 셈이라 조언이 될 수 없다 —
    질문 해석 자체가 어긋난 경우다."""
    rows = parse_rationale("a | NONE | CONDITION\nb | NONE | CONDITION", Q)
    assert find_unsupported(rows, select_count=2) is None


def test_malformed_lines_are_dropped():
    rows = parse_rationale(
        "설명을 붙이면 안 되는데 붙였다\n"
        "T1.school | schools | REQUESTED\n"
        "짝 없는 줄", Q)
    assert len(rows) == 1


def test_verdict_with_trailing_text_still_parses():
    """모델이 'REQUESTED (결과 컬럼)'처럼 덧붙이는 경우가 있다."""
    rows = parse_rationale("T1.school | schools | REQUESTED (결과로 요구됨)", Q)
    assert rows[0].is_requested
    assert find_unsupported(rows, select_count=1) is None


def test_debug_line_marks_fabricated_quote():
    rows = parse_rationale("T1.x | 존재하지 않는 인용 | REQUESTED", Q)
    assert "지어낸 인용" in rows[0].debug_line()
    rows = parse_rationale("T1.x | NONE | CONDITION", Q)
    assert "근거 없음" in rows[0].debug_line()
