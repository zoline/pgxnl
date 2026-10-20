"""생성된 SQL이 질문을 충실히 따랐는지 검사하는 로직 테스트.

동기(실측, seq 461): 질문이 `"...for the 2014-2015 academic year?"` 인데 모델이
`"Academic Year" = '2014-15'` 를 생성해 0건을 반환했다. 27B에서 12회 연속 재현됐고
gpt-oss-120b·35B는 맞혔다 — 27B가 학년도를 미국식 축약으로 정규화하는 습성이다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.question_guard import check_column_order, check_literals
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

Q461 = (
    "How many students from the ages of 5 to 17 are enrolled at the State Special School "
    "school in Fremont for the 2014-2015 academic year?"
)
E461 = "State Special School means EdOpsCode = 'SSS'"


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def check(parser, sql: str, question: str, evidence: str | None = None):
    return check_literals(parser.to_ir(parser.parse(" ".join(sql.split()))), question, evidence)


def test_detects_the_real_2014_15_mutation(parser):
    sql = """SELECT x FROM frpm T1 JOIN schools T2 ON T1.cdscode = T2.cdscode
             WHERE T2.edopscode = 'SSS' AND T2.city = 'Fremont' AND T1."Academic Year" = '2014-15'"""
    found = check(parser, sql, Q461, E461)
    assert [f.literal for f in found] == ["2014-15"]
    assert found[0].source == "2014-2015"
    assert "질문의 값을 그대로 쓰세요" in found[0].message()


def test_correct_literal_is_not_flagged(parser):
    sql = """SELECT x FROM frpm T1 WHERE T1."Academic Year" = '2014-2015'"""
    assert check(parser, sql, Q461, E461) == []


def test_code_values_from_evidence_are_not_flagged(parser):
    """evidence·glossary에서 온 코드값은 질문에 없는 게 정상이다 — 오탐이 나면 안 된다."""
    sql = "SELECT school FROM schools WHERE doc = '31' AND edopscode = 'SSS'"
    q = "Which state special schools have the highest number of enrollees?"
    e = "State Special Schools refers to DOC = 31; State Special School means EdOpsCode = 'SSS'"
    assert check(parser, sql, q, e) == []


def test_literal_appearing_verbatim_in_question_is_fine(parser):
    sql = "SELECT phone FROM schools WHERE district = 'Fresno Unified'"
    assert check(parser, sql, "What is the telephone number for the school in Fresno Unified?") == []


def test_detects_widened_literal(parser):
    """질문의 값에 없는 말을 덧붙인 경우도 변형이다."""
    sql = "SELECT school FROM schools WHERE city = 'Riverside Unified'"
    found = check(parser, sql, "Name schools in Riverside which the average math score is over 400")
    assert [f.literal for f in found] == ["Riverside Unified"]
    assert found[0].source == "Riverside"


def test_short_literals_are_skipped(parser):
    """'F', 'S' 같은 코드값은 우연히 비슷해지기 쉬워 검사 대상에서 뺀다."""
    sql = "SELECT school FROM schools WHERE virtual = 'F'"
    assert check(parser, sql, "List the exclusively virtual schools in Fremont") == []


def test_unrelated_literal_is_not_flagged(parser):
    """질문에 비슷한 문자열이 아예 없으면 스키마·glossary에서 온 값으로 보고 넘어간다."""
    sql = "SELECT school FROM schools WHERE fundingtype = 'Directly funded'"
    assert check(parser, sql, "List the charter schools in Alameda county") == []


def test_having_clause_literals_are_checked(parser):
    sql = """SELECT city, count(*) FROM schools GROUP BY city HAVING max(fundingtype) = 'Locally fundedd'"""
    found = check(parser, sql, "Which cities have Locally funded schools?")
    assert [f.literal for f in found] == ["Locally fundedd"]


def test_select_clause_literals_are_ignored(parser):
    """SELECT 절의 문자열은 별칭·상수라 질문에 없어도 정상이다."""
    sql = "SELECT 'total' AS label, count(*) FROM schools WHERE city = 'Fremont'"
    assert check(parser, sql, "How many schools are in Fremont?") == []


def test_duplicate_literals_reported_once(parser):
    sql = """SELECT x FROM frpm WHERE "Academic Year" = '2014-15' OR "Academic Year" = '2014-15'"""
    assert len(check(parser, sql, Q461, E461)) == 1


def test_non_select_returns_nothing(parser):
    ir = parser.to_ir(parser.parse("UPDATE schools SET city = 'X'"))
    assert ir is None or check_literals(ir, "irrelevant") == []


# --------------------------------------------------------------- SELECT 컬럼 순서

Q450 = (
    "What is the complete address of the school with the lowest excellence rate? "
    "Indicate the Street, City, Zip and State."
)


def order(parser, sql: str, question: str):
    return check_column_order(parser.to_ir(parser.parse(" ".join(sql.split()))), question)


def test_detects_the_real_450_order_mismatch(parser):
    """실측: 질문은 Zip 다음 State인데 모델이 State, Zip 순으로 냈다."""
    r = order(parser, "SELECT T1.street, T1.city, T1.state, T1.zip FROM schools T1", Q450)
    assert r is not None
    assert r.expected == ["street", "city", "zip", "state"]
    assert r.actual == ["street", "city", "state", "zip"]
    assert "질문에 언급된 순서대로" in r.message()


def test_matching_order_is_fine(parser):
    assert order(parser, "SELECT T1.street, T1.city, T1.zip, T1.state FROM schools T1", Q450) is None


def test_columns_absent_from_question_are_ignored(parser):
    """질문에 이름이 없는 컬럼은 순서를 따질 근거가 없다 — 끼어 있어도 무시한다."""
    sql = "SELECT T1.street, T1.cdscode, T1.city, T1.zip, T1.state FROM schools T1"
    assert order(parser, sql, Q450) is None


def test_aggregates_are_excluded(parser):
    """집계식은 질문에 그대로 등장하지 않으므로 위치를 잴 수 없다."""
    sql = "SELECT count(*), T1.city FROM schools T1 GROUP BY T1.city"
    assert order(parser, sql, "How many schools are in each city?") is None


def test_single_matched_column_is_not_judged(parser):
    assert order(parser, "SELECT T1.street FROM schools T1", Q450) is None


def test_quoted_column_with_space(parser):
    q = "List the School Name and the City of each school."
    ok = order(parser, 'SELECT T1."School Name", T1.city FROM frpm T1', q)
    bad = order(parser, 'SELECT T1.city, T1."School Name" FROM frpm T1', q)
    assert ok is None
    assert bad is not None and bad.expected == ["school name", "city"]


def test_word_boundary_prevents_false_match(parser):
    """'state'가 'estate'에 걸리면 위치가 틀어진다."""
    q = "Show the city and state of the real estate office."
    assert order(parser, "SELECT T1.city, T1.state FROM t T1", q) is None


def test_non_select_is_safe(parser):
    ir = parser.to_ir(parser.parse("UPDATE schools SET city = 'X'"))
    assert ir is None or check_column_order(ir, Q450) is None


# ---- LIKE 패턴은 값이 아니다 (BIRD 444) ----

Q444 = ("Name schools in Riverside which the average of average math score for SAT is "
        "grater than 400, what is the funding type of these schools?")
E444 = ("Average of average math = sum(average math scores) / count(schools); compute it with "
        "GROUP BY per school and filter with HAVING. Riverside here refers to the school "
        "district name (District Name starts with 'Riverside'), not the county.")


def test_like_패턴의_와일드카드는_변형이_아니다(parser):
    """실측 BIRD 444: 모델이 맞게 낸 `LIKE 'Riverside%'` 를 가드가 되돌리게 해
    `LIKE 'Riverside'` 가 됐고 결과가 0행이 됐다 (실제 값은 `Riverside Unified`)."""
    sql = """SELECT T1.sname FROM satscores T1 JOIN schools T2 ON T1.cds = T2.cdscode
             WHERE T1.dname LIKE 'Riverside%'"""
    assert check(parser, sql, Q444, E444) == []


def test_앞뒤_와일드카드도_마찬가지(parser):
    sql = "SELECT a FROM t WHERE t.dname LIKE '%Riverside%'"
    assert check(parser, sql, Q444, E444) == []


def test_ilike도_패턴으로_본다(parser):
    sql = "SELECT a FROM t WHERE t.dname ILIKE 'Riverside%'"
    assert check(parser, sql, Q444, E444) == []


def test_패턴이어도_질문에_없는_값이면_잡는다(parser):
    """와일드카드를 뗀 뒤에도 질문과 다르면 여전히 변형이다."""
    sql = "SELECT a FROM t WHERE t.dname LIKE 'Riverdale%'"
    found = check(parser, sql, Q444, E444)
    assert len(found) == 1 and found[0].literal == "Riverdale%"


def test_같은_값이라도_등호_비교면_패턴이_아니다(parser):
    """`= 'Riverside%'` 는 진짜로 그 글자를 찾는 것이라 변형이 맞다."""
    sql = "SELECT a FROM t WHERE t.dname = 'Riverside%'"
    found = check(parser, sql, Q444, E444)
    assert len(found) == 1 and found[0].literal == "Riverside%"


def test_와일드카드뿐인_패턴은_넘어간다(parser):
    sql = "SELECT a FROM t WHERE t.dname LIKE '%%%'"
    assert check(parser, sql, Q444, E444) == []


# ── 따옴표로 묶은 값의 일부만 쓴 경우 (BIRD codebase_community 314·316, 2026-10-14) ──

def test_quoted_value_with_trailing_punctuation_dropped(parser):
    q = "Name the user that commented 'thank you user93!'"
    found = check(parser, "SELECT userid FROM comments WHERE text = 'thank you user93'", q,
                   '"thank you user93" is the Text of comment')
    assert len(found) == 1 and found[0].quoted and found[0].source == "thank you user93!"
    assert "문장부호까지" in found[0].message()


def test_quoted_title_question_mark_dropped(parser):
    q = "Who is the owner of the post titled 'Open source tools for visualizing multi-dimensional data?'"
    found = check(parser, "SELECT 1 FROM posts WHERE title = 'Open source tools for visualizing multi-dimensional data'", q)
    assert [f.source for f in found] == ["Open source tools for visualizing multi-dimensional data?"]


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM comments WHERE text = 'thank you user93!'",           # 그대로
    "SELECT 1 FROM comments WHERE text LIKE '%thank you user93%'",       # 패턴은 일부가 정상
])
def test_quoted_value_used_whole_or_as_pattern_is_fine(parser, sql):
    assert check(parser, sql, "Name the user that commented 'thank you user93!'") == []


def test_apostrophe_is_not_a_quote(parser):
    assert check(parser, "SELECT 1 FROM cards WHERE name = 'Chosen'", "Is Ancestor's Chosen legal?") == []


def test_value_quoted_separately_is_fine(parser):
    q = 'How many cards with original type of "Summon - Angel" have subtype other than "Angel"?'
    sql = "SELECT COUNT(*) FROM cards WHERE originaltype = 'Summon - Angel' AND subtypes <> 'Angel'"
    assert check(parser, sql, q) == []


def test_evidence_quote_does_not_excuse_question_quote(parser):
    # 316: 가드가 받는 문장은 질문 + evidence. evidence 의 '?' 없는 표기가 "따로 준 값"으로 통과하면 안 된다.
    q = "Who is the owner of the post titled 'Open source tools for visualizing multi-dimensional data?'"
    full = q + " 'Open source tools for visualizing multi-dimensional data' is the Title of Post;"
    sql = "SELECT 1 FROM posts WHERE title = 'Open source tools for visualizing multi-dimensional data'"
    assert check(parser, sql, full) == []  # 질문만 구분하지 않으면 놓친다
    found = check_literals(parser.to_ir(parser.parse(sql)), full, quote_source=q)
    assert [f.source for f in found] == ["Open source tools for visualizing multi-dimensional data?"]
