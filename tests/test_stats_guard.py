"""stats_guard 단위 테스트 — 생성된 SQL을 컬럼 통계와 대조한다.

`question_guard`와 짝이지만 근거가 다르다: 저쪽은 질문 텍스트만 보고, 이쪽은 pg_stats의
null_frac을 본다. 그래서 테스트도 통계 조회를 페이크로 주입해 검증한다.

실측 기준값(california_schools.schools)을 그대로 쓴다 — 임계값이 실제 분포에서 의도대로
갈리는지 보기 위함이다:
    admemail1 0.340 / admemail2 0.976 / admemail3 0.998
"""
import pytest

from pgxnl.agent.stats_guard import (
    DEFAULT_THRESHOLD,
    check_ambiguous_columns,
    check_empty_columns,
    parse_rule,
    triggered_by,
)
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

_NULL_FRAC = {
    ("schools", "admemail1"): 0.33992988,
    ("schools", "admemail2"): 0.97602624,
    ("schools", "admemail3"): 0.99762523,
    ("schools", "cdscode"): 0.0,
    ("frpm", "cdscode"): 0.0,
}


def _lookup(recorded=None):
    async def lookup(schema, table, column):
        if recorded is not None:
            recorded.append((schema, table, column))
        return _NULL_FRAC.get((table.lower(), column.lower()))
    return lookup


@pytest.fixture(scope="module")
def parser():
    return AntlrPostgresParser()


def _ir_and_aliases(parser, sql):
    stmt = parser.parse(sql)
    return parser.to_ir(stmt), stmt.alias_to_table


_SQL_467 = (
    'SELECT T2."AdmEmail1", T2."AdmEmail2", T2."AdmEmail3" '
    'FROM frpm AS T1 INNER JOIN schools AS T2 ON T1."CDSCode" = T2."CDSCode" '
    "WHERE T2.\"County\" = 'San Bernardino'"
)


async def test_flags_almost_empty_column_in_select(parser):
    # BIRD 467의 실제 실패 양상: 필터는 gold와 같은데 AdmEmail3 한 컬럼이 더 붙어 틀린다.
    # 그 컬럼은 99.8%가 NULL이다. 이 문항의 gold는 AdmEmail1, AdmEmail2를 남긴다.
    ir, aliases = _ir_and_aliases(parser, _SQL_467)

    found = await check_empty_columns(
        ir, question="What are the valid e-mail addresses of the administrator?",
        alias_to_table=aliases, lookup=_lookup(), triggers=["valid"], threshold=0.99,
        default_schema="california_schools",
    )

    assert [w.column for w in found] == ["admemail3"]
    w = found[0]
    assert w.table == "schools"
    assert w.trigger == "valid"
    assert "99.8%" in w.message()
    # 코드가 컬럼을 지우는 게 아니라 모델에게 되돌리는 것이므로, 문구가 판단을 요청해야 한다.
    assert "다시 판단하세요" in w.message()


async def test_threshold_choice_decides_whether_gold_column_is_flagged(parser):
    """임계값을 실제 분포에 맞춰 골라야 한다는 것을 고정한다.

    seq 467의 gold는 AdmEmail2(null_frac 0.976)를 **남긴다**. 그래서 기본값 0.95를 쓰면
    gold가 유지한 컬럼까지 지적한다 — 오탐이다. 0.99로 올려야 실제로 죽은 컬럼
    (AdmEmail3, 0.998)만 걸린다. 반복 그룹 컬럼은 이렇게 0.97~0.99 사이에 몰려 있어
    임계값 한 자리가 판정을 가른다.
    """
    ir, aliases = _ir_and_aliases(parser, _SQL_467)

    at_95 = await check_empty_columns(
        ir, question="valid e-mail addresses", alias_to_table=aliases, lookup=_lookup(),
        triggers=["valid"], threshold=0.95, default_schema="california_schools",
    )
    at_99 = await check_empty_columns(
        ir, question="valid e-mail addresses", alias_to_table=aliases, lookup=_lookup(),
        triggers=["valid"], threshold=0.99, default_schema="california_schools",
    )

    assert sorted(w.column for w in at_95) == ["admemail2", "admemail3"]  # gold 컬럼까지 걸린다
    assert sorted(w.column for w in at_99) == ["admemail3"]
    assert DEFAULT_THRESHOLD == 0.99  # 기본값은 오탐이 없는 쪽으로 정해져 있다
    # 정상적으로 듬성듬성한 컬럼(0.340)은 어느 쪽에서도 안 걸린다.
    assert "admemail1" not in {w.column for w in at_95}


async def test_no_trigger_word_means_no_stats_lookup(parser):
    # 발동 낱말이 없으면 통계를 아예 조회하지 않아야 한다 — 모든 질의에 pg_stats를 때리면
    # 비용이 붙고, 질문이 값의 존재를 요구하지 않았는데 NULL 많은 컬럼을 지적할 이유도 없다.
    ir, aliases = _ir_and_aliases(parser, _SQL_467)
    calls = []

    found = await check_empty_columns(
        ir, question="What are the e-mail addresses of the administrator?",
        alias_to_table=aliases, lookup=_lookup(calls), triggers=["valid"],
        default_schema="california_schools",
    )

    assert found == []
    assert calls == []


@pytest.mark.parametrize("question", [
    "Accounts with loan validity more than 12 months?",   # BIRD 474 — duration > 12, NULL과 무관
    "List the invalid rows.",                             # 뜻이 정반대
])
async def test_word_boundary_prevents_false_trigger(parser, question):
    ir, aliases = _ir_and_aliases(parser, _SQL_467)

    found = await check_empty_columns(
        ir, question=question, alias_to_table=aliases, lookup=_lookup(),
        triggers=["valid"], default_schema="california_schools",
    )

    assert found == []


async def test_missing_stats_is_not_treated_as_empty(parser):
    # ANALYZE가 안 돌았으면 null_frac이 None이다. 없는 것을 "비어 있다"로 읽으면
    # 통계가 없는 모든 컬럼을 지적하게 된다.
    ir, aliases = _ir_and_aliases(parser, _SQL_467)

    async def no_stats(schema, table, column):
        return None

    found = await check_empty_columns(
        ir, question="valid e-mail", alias_to_table=aliases, lookup=no_stats,
        triggers=["valid"], default_schema="california_schools",
    )

    assert found == []


async def test_lookup_failure_is_skipped_not_raised(parser):
    # 보조 검사가 필수 경로(SQL 생성)를 막으면 안 된다(설계 원칙 1).
    ir, aliases = _ir_and_aliases(parser, _SQL_467)

    async def broken(schema, table, column):
        raise RuntimeError("pg_stats 조회 실패")

    found = await check_empty_columns(
        ir, question="valid e-mail", alias_to_table=aliases, lookup=broken,
        triggers=["valid"], default_schema="california_schools",
    )

    assert found == []


async def test_aggregate_expressions_are_ignored(parser):
    # 식의 결과가 NULL인지는 컬럼 통계로 판단할 수 없다.
    sql = 'SELECT count(T2."AdmEmail3"), T2."AdmEmail1" FROM schools AS T2'
    ir, aliases = _ir_and_aliases(parser, sql)
    calls = []

    found = await check_empty_columns(
        ir, question="valid e-mail", alias_to_table=aliases, lookup=_lookup(calls),
        triggers=["valid"], default_schema="california_schools",
    )

    assert found == []
    assert ("california_schools", "schools", "admemail3") not in calls


async def test_unqualified_columns_are_ignored(parser):
    # 한정하지 않은 컬럼은 어느 테이블 것인지 정하려면 스코프 분석이 필요하다 —
    # 잘못 판단하면 멀쩡한 SQL에 경고를 단다(validation._bind_columns와 같은 판단).
    sql = 'SELECT "AdmEmail3" FROM schools'
    ir, aliases = _ir_and_aliases(parser, sql)

    found = await check_empty_columns(
        ir, question="valid e-mail", alias_to_table=aliases, lookup=_lookup(),
        triggers=["valid"], default_schema="california_schools",
    )

    assert found == []


# ------------------------------------------------------------------ 트리거 / 규칙 파싱

def test_triggered_by_returns_matched_word():
    assert triggered_by("the valid e-mail addresses", ["valid", "유효한"]) == "valid"
    assert triggered_by("유효한 이메일 주소", ["valid", "유효한"]) == "유효한"
    assert triggered_by("loan validity", ["valid"]) is None
    assert triggered_by("anything", []) is None


def test_parse_rule_reads_triggers_and_threshold():
    assert parse_rule({"trigger": ["valid"], "threshold": 0.9}) == (["valid"], 0.9)
    assert parse_rule({"trigger": "valid"}) == (["valid"], DEFAULT_THRESHOLD)


def test_parse_rule_returns_none_without_triggers():
    # 트리거가 비면 어떤 질문에도 발동하지 않는다. 조용히 "전부 발동"으로 해석하면
    # 등록만 해두고 잊은 규칙이 모든 질의에 개입하게 된다.
    assert parse_rule({"threshold": 0.95}) is None
    assert parse_rule({"trigger": []}) is None
    assert parse_rule({"trigger": ["  "]}) is None


def test_parse_rule_falls_back_on_bad_threshold():
    assert parse_rule({"trigger": ["valid"], "threshold": "높게"}) == (["valid"], DEFAULT_THRESHOLD)


# ------------------------------------------------- 값이 여러 컬럼에 있을 때 (컬럼 선택 모호)

_SQL_445_CITY = (
    'SELECT T2."School Name" FROM frpm AS T1 INNER JOIN schools AS T2 '
    "ON T1.cdscode = T2.cdscode WHERE T2.city = 'Monterey'"
)
_SQL_445_COUNTY = _SQL_445_CITY.replace("T2.city", "T2.county")

#: 실측(california_schools): 'Monterey'를 흔한 값으로 갖는 저카디널리티 컬럼들.
#: city(1165종)/mailcity(1132종)는 MCV 상위 100개에 없어 후보에 안 들어온다 — 의도한
#: 방향이다. "58개 카운티 중 하나"는 범주를 뜻하지만 "1165개 도시 중 하나"는 약하다.
_MONTEREY_COLUMNS = ["schools.county", "frpm.County Name", "satscores.cname"]


def _col_lookup(mapping, recorded=None):
    """값 -> 그 값을 흔한 값으로 갖는 컬럼 목록. 위쪽 `_lookup`(null_frac 조회)과 다른 것이라
    이름을 구분한다."""
    async def lookup(schema, value):
        if recorded is not None:
            recorded.append(value)
        return mapping.get(value, [])
    return lookup


async def test_flags_value_that_is_common_in_other_columns(parser):
    # BIRD 445: 질문은 "in Monterey"라고만 하는데 모델은 city(16행)를, gold는 county(247행)를
    # 골랐다. 질문·evidence·스키마 어디에도 근거가 없고 데이터를 봐야 갈린다.
    ir, aliases = _ir_and_aliases(parser, _SQL_445_CITY)

    found = await check_ambiguous_columns(
        ir, alias_to_table=aliases, lookup=_col_lookup({"Monterey": _MONTEREY_COLUMNS}),
        schema="california_schools",
    )

    assert len(found) == 1
    w = found[0]
    assert w.literal == "Monterey"
    assert "schools.county" in w.candidates
    # 판정하지 않는다 — 어느 쪽을 쓰라고 하지 않고 사실만 돌려준다.
    assert "다시 판단하세요" in w.message()
    assert "쓰세요" not in w.message()


async def test_no_warning_when_sql_already_uses_a_candidate_column(parser):
    # gold처럼 county를 쓰고 있으면 알릴 게 없다. 30문항 실측에서 gold 13건 모두 이 경우였다.
    ir, aliases = _ir_and_aliases(parser, _SQL_445_COUNTY)

    found = await check_ambiguous_columns(
        ir, alias_to_table=aliases, lookup=_col_lookup({"Monterey": _MONTEREY_COLUMNS}),
        schema="california_schools",
    )

    assert found == []


async def test_single_candidate_is_not_ambiguous(parser):
    # 그 값을 갖는 컬럼이 하나뿐이면 고를 여지가 없다.
    ir, aliases = _ir_and_aliases(parser, _SQL_445_CITY)

    found = await check_ambiguous_columns(
        ir, alias_to_table=aliases, lookup=_col_lookup({"Monterey": ["schools.county"]}),
        schema="california_schools",
    )

    assert found == []


async def test_ambiguous_short_literals_are_skipped(parser):
    # 'F', 'S' 같은 코드값은 우연히 여러 컬럼에 걸리기 쉽다.
    sql = "SELECT T1.school FROM schools AS T1 WHERE T1.virtual = 'F'"
    ir, aliases = _ir_and_aliases(parser, sql)
    calls = []

    found = await check_ambiguous_columns(
        ir, alias_to_table=aliases, lookup=_col_lookup({}, calls), schema="california_schools",
    )

    assert found == [] and calls == []


async def test_ambiguous_lookup_failure_is_skipped_not_raised(parser):
    ir, aliases = _ir_and_aliases(parser, _SQL_445_CITY)

    async def broken(schema, value):
        raise RuntimeError("pg_stats 조회 실패")

    found = await check_ambiguous_columns(
        ir, alias_to_table=aliases, lookup=broken, schema="california_schools",
    )

    assert found == []
