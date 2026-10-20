"""BIRD 평가 채점 로직(_results_equal) 단위 테스트.

배경: gold SQL(BIRD 원본이 SQLite→Postgres로 이식되며 CAST(x AS REAL) 사용)과
생성 SQL이 논리적으로 같아도 REAL(float4)/DOUBLE PRECISION(float8) 캐스트 차이로
소수점 8자리 이후가 미세하게 달라지는 걸 실측으로 확인했다(pgxllm에서도 동일 문제를
round(5)로 해결한 전례가 있음). 문자열 완전일치 비교는 이런 경우를 오답으로 잘못
채점(false negative)한다.
"""
from decimal import Decimal

from pgxnl.agent.evaluation.bird import _results_equal


def test_exact_match_still_passes():
    assert _results_equal([{"n": "Gina"}], [{"n": "Gina"}])


def test_case_and_whitespace_insensitive_for_text():
    assert _results_equal([{"n": "  Gina  "}], [{"n": "gina"}])


def test_float_precision_noise_from_real_vs_double_cast_absorbed():
    # 실측 케이스: 같은 값인데 REAL/DOUBLE PRECISION 캐스트 차이로 소수점 8자리
    # 이후가 다름 (0.9049080014228821 vs 0.9049079754601227, 차이 2.6e-8)
    gold = [{"max_eligible_free_rate": 0.9049080014228821}]
    pred = [{"max_eligible_free_rate": 0.9049079754601227}]
    assert _results_equal(gold, pred)


def test_integer_and_whole_float_are_equal():
    # 정수(25)와 정수값을 갖는 float(25.0)이 다른 문자열로 비교되지 않아야 함
    assert _results_equal([{"n": 25}], [{"n": 25.0}])


def test_decimal_and_float_are_equal():
    assert _results_equal([{"n": Decimal("0.30000")}], [{"n": 0.3}])


def test_genuinely_different_values_still_fail():
    assert not _results_equal([{"n": 0.30}], [{"n": 0.40}])


def test_row_order_does_not_matter():
    r1 = [{"n": 1}, {"n": 2}]
    r2 = [{"n": 2}, {"n": 1}]
    assert _results_equal(r1, r2)


def test_none_values_handled():
    assert _results_equal([{"n": None}], [{"n": None}])
    assert not _results_equal([{"n": None}], [{"n": 0}])


def test_null_and_numeric_mixed_in_same_column_does_not_crash():
    # 실측 케이스: LEFT JOIN 결과처럼 같은 컬럼에 NULL과 숫자가 섞여 있으면(NULL은
    # _norm_value가 빈 문자열로 바꾸므로), 정렬 키가 문자열로 통일돼 있지 않으면
    # sorted()가 str과 int/float를 직접 비교하려다 TypeError를 던진다 — 이 경우
    # 문항 전체가 "채점 불가 오류"로 조용히 넘어가 진짜 EX 결과를 영영 확인할 수
    # 없었다(BIRD 문항 446번에서 재현). 여러 행에 NULL/숫자가 섞여도 크래시 없이
    # 정상 비교돼야 한다.
    gold = [{"score": None}, {"score": 605}, {"score": 720}]
    pred = [{"score": 720}, {"score": None}, {"score": 605}]
    assert _results_equal(gold, pred)  # 순서만 다르고 내용은 같음 -> True, 크래시 없음
    assert not _results_equal(gold, [{"score": None}, {"score": 605}, {"score": 999}])
