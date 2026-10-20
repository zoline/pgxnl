"""SELECT 컬럼 순서 재배열 규칙 테스트.

배경: 평가의 결과 비교가 튜플 위치를 보므로 값이 같아도 순서가 다르면 오답이다.
프롬프트 규칙 id=22가 같은 내용을 지시하지만 지켜지지 않는 것이 실측으로 확인됐다.

seq 450을 초기 사례로 들었으나 방향이 반대였다(2026-09-07 정정): 질문은
`"Street, City, Zip and State"`, evidence는 `"complete address has Street, City, State,
Zip code"`이고 **gold는 evidence 쪽**(`street, city, state, zip`)이다. 즉 그 문항에서
질문 순서로 재배열하면 정답을 깨뜨린다 — 그래서 충돌 시 기본 동작이 "손대지 않음"이다.
"""
from __future__ import annotations

import re

import pytest

from pgxnl.agent.canonicalize import ColumnOrderRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

Q450 = (
    "What is the complete address of the school with the lowest excellence rate? "
    "Indicate the Street, City, Zip and State."
)


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def canon(parser, sql: str, question: str = Q450) -> str:
    return canonicalize_sql(sql, parser, [ColumnOrderRule(question)])


def test_reorders_to_question_order(parser):
    assert canon(parser, "SELECT T1.street, T1.city, T1.state, T1.zip FROM schools T1") == (
        "SELECT T1.street, T1.city, T1.zip, T1.state FROM schools T1"
    )


def test_already_in_question_order_is_untouched(parser):
    sql = "SELECT T1.street, T1.city, T1.zip, T1.state FROM schools T1"
    assert canon(parser, sql) == sql


def test_columns_absent_from_question_keep_their_slot(parser):
    """질문에 없는 컬럼은 옮길 근거가 없으므로 제자리를 지킨다."""
    assert canon(parser, "SELECT T1.street, T1.cdscode, T1.state, T1.zip FROM schools T1") == (
        "SELECT T1.street, T1.cdscode, T1.zip, T1.state FROM schools T1"
    )


def test_aggregate_stays_in_place(parser):
    """집계식은 질문에 그대로 등장하지 않아 순서 판정에서 빠진다."""
    assert canon(parser, "SELECT count(*), T1.state, T1.zip FROM schools T1") == (
        "SELECT count(*), T1.zip, T1.state FROM schools T1"
    )


def test_subquery_is_skipped(parser):
    """어느 SELECT의 목록인지 구분이 필요해 보수적으로 건너뛴다."""
    sql = "SELECT T1.state, T1.zip FROM schools T1 WHERE T1.cdscode IN (SELECT cds FROM satscores)"
    assert canon(parser, sql) == sql


def test_quoted_column_name_with_space(parser):
    assert canon(parser, 'SELECT T1.city, T1."School Name" FROM frpm T1',
                 "List the School Name and the City.") == (
        'SELECT T1."School Name", T1.city FROM frpm T1'
    )


def test_single_matched_column_is_untouched(parser):
    sql = "SELECT T1.street, T1.cdscode FROM schools T1"
    assert canon(parser, sql) == sql


def test_empty_question_disables_the_rule(parser):
    """질문이 없는 경로(SQL 직접 실행 등)에서는 판정 근거가 없다."""
    sql = "SELECT T1.state, T1.zip FROM schools T1"
    assert canon(parser, sql, question="") == sql


def test_non_select_is_untouched(parser):
    sql = "UPDATE schools SET city = 'X'"
    assert canon(parser, sql) == sql


def test_word_boundary_prevents_false_match(parser):
    """'state'가 'estate'에 걸리면 엉뚱한 위치로 재배열된다."""
    q = "Show the city and state of the real estate office."
    sql = "SELECT T1.city, T1.state FROM t T1"
    assert canon(parser, sql, q) == sql


def test_rule_is_registered_from_store():
    from pgxnl.agent.canonicalize import load_rules_from_store
    from pgxnl.governance.rules import Rule

    r = Rule(id=1, target_name=None, rule_type="canonicalization",
             definition={"kind": "column_order"}, enabled=True, updated_at=None)
    assert len(load_rules_from_store([r], question="질문 있음")) == 1
    # 질문이 없으면 판정할 수 없으므로 건너뛴다
    assert load_rules_from_store([r]) == []


# --------------------------------------------------------------- evidence 충돌

E450 = "Execellence Rate = NumGE1500 / NumTstTakr; complete address has Street, City, State, Zip code"


def test_conflicting_evidence_order_blocks_reordering(parser):
    """질문과 evidence가 다른 순서를 말하면 어느 쪽이 옳은지 판단할 수 없다.

    실측 seq 450: 질문은 "Street, City, Zip and State", evidence는 "Street, City,
    State, Zip code" 이고 gold는 evidence를 따랐다. 초판은 질문만 보고 재배열해
    오히려 정답이던 순서를 깨뜨렸다.
    """
    sql = "SELECT T1.street, T1.city, T1.state, T1.zip FROM schools T1"
    assert canonicalize_sql(sql, parser, [ColumnOrderRule(Q450, E450)]) == sql


def test_agreeing_evidence_allows_reordering(parser):
    sql = "SELECT T1.street, T1.city, T1.state, T1.zip FROM schools T1"
    e = "complete address has Street, City, Zip, State"
    assert canonicalize_sql(sql, parser, [ColumnOrderRule(Q450, e)]) == (
        "SELECT T1.street, T1.city, T1.zip, T1.state FROM schools T1"
    )


def test_evidence_without_those_columns_is_not_a_conflict(parser):
    """evidence가 그 컬럼들을 언급하지 않으면 비교 대상이 아니다 — 질문 순서를 따른다."""
    sql = "SELECT T1.street, T1.city, T1.state, T1.zip FROM schools T1"
    e = "Excellence Rate = NumGE1500 / NumTstTakr"
    assert canonicalize_sql(sql, parser, [ColumnOrderRule(Q450, e)]) == (
        "SELECT T1.street, T1.city, T1.zip, T1.state FROM schools T1"
    )


def test_store_passes_evidence_through():
    from pgxnl.agent.canonicalize import load_rules_from_store
    from pgxnl.governance.rules import Rule

    r = Rule(id=1, target_name=None, rule_type="canonicalization",
             definition={"kind": "column_order"}, enabled=True, updated_at=None)
    rules = load_rules_from_store([r], question=Q450, evidence=E450)
    assert len(rules) == 1
    assert rules[0]._evidence == E450


# ------------------------------------------------- 질문 vs evidence 순서 충돌 정책(on_conflict)

def _order(sql: str) -> list[str]:
    """SELECT 절의 컬럼 이름만 순서대로."""
    body = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL).group(1)
    return [item.strip().split(".")[-1].strip('"').lower() for item in body.split(",")]


# 실측 표본(2026-09-07, 500문항 전수). 두 문항의 evidence는 성격이 다르고 gold도 갈린다 —
# 그래서 기본값이 "손대지 않음"이고, 정책은 규칙 정의로 바꿀 수 있게만 열어 뒀다.
_Q_450 = "What is the complete address of the school? Indicate the Street, City, Zip and State."
_E_450 = "complete address has Street, City, State, Zip code"
_SQL_450 = "SELECT T2.street, T2.city, T2.zip, T2.state FROM schools AS T2"


def test_conflict_skip_is_the_default(parser):
    # 질문(zip,state)과 evidence(state,zip)가 충돌한다 — 기본값은 아무것도 안 한다.
    stmt = parser.parse(_SQL_450)
    assert ColumnOrderRule(_Q_450, _E_450).collect_edits(stmt) == []


def test_conflict_evidence_reorders_to_evidence_order(parser):
    # seq 450의 gold는 evidence 순서(street, city, state, zip)다.
    out = canonicalize_sql(_SQL_450, parser, [ColumnOrderRule(_Q_450, _E_450, on_conflict="evidence")])
    assert _order(out) == ["street", "city", "state", "zip"]


def test_conflict_question_keeps_question_order(parser):
    # seq 394의 gold는 질문 순서를 따랐다 — 그 정책도 고를 수 있어야 한다.
    sql = "SELECT T2.format, T1.name FROM cards AS T1 INNER JOIN legalities AS T2 ON T1.uuid = T2.uuid"
    question = "List all of the cards name and its banned play format."
    evidence = "play format refers to format; cards name refers to name"

    out = canonicalize_sql(sql, parser, [ColumnOrderRule(question, evidence, on_conflict="question")])

    assert _order(out) == ["name", "format"]


def test_evidence_silent_on_order_falls_back_to_question(parser):
    # evidence가 그 컬럼들을 다 언급하지 않으면 순서에 대해 말한 게 없는 것이다 —
    # 정책과 무관하게 질문 순서를 쓴다.
    sql = "SELECT T2.state, T2.city FROM schools AS T2"
    question = "Indicate the City and State."

    for policy in ("skip", "evidence", "question"):
        out = canonicalize_sql(sql, parser, [ColumnOrderRule(question, "무관한 참고 정보", on_conflict=policy)])
        assert _order(out) == ["city", "state"], policy


def test_unknown_policy_falls_back_to_skip(parser):
    stmt = parser.parse(_SQL_450)
    assert ColumnOrderRule(_Q_450, _E_450, on_conflict="아무거나").collect_edits(stmt) == []
