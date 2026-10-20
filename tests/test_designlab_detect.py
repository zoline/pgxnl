"""이름 기반 후보 추출 테스트 (`designlab.detect`).

함수 종속을 전수 탐색하면 컬럼 수에 지수적이다(BIRD `schools`만 49개 컬럼) —
이름 패턴으로 후보를 먼저 좁히는 것이 이 모듈의 존재 이유다. 데이터 검증은
`analyzer`가 한다.
"""
from __future__ import annotations

from pgxnl.agent.designlab.detect import (
    find_code_name_pairs,
    find_duplicate_concepts,
    find_repeating_groups,
)

BIRD = {
    "schools": ["cdscode", "county", "district", "school", "soc", "soctype", "doc", "doctype",
                "edopscode", "edopsname", "admfname1", "admfname2", "admfname3",
                "admemail1", "admemail2", "admemail3"],
    "frpm": ["cdscode", "County Name", "District Name", "School Name", "School Type",
             "Enrollment (K-12)"],
    "satscores": ["cds", "sname", "enroll12", "numge1500"],
}


def test_repeating_groups_are_found():
    got = {(r.table, r.base, tuple(r.columns)) for r in find_repeating_groups(BIRD)}
    assert ("schools", "admfname", ("admfname1", "admfname2", "admfname3")) in got
    assert ("schools", "admemail", ("admemail1", "admemail2", "admemail3")) in got


def test_single_numbered_column_is_not_a_repeating_group():
    """`enroll12`는 12학년을 뜻하는 하나짜리 컬럼이다 — 반복 그룹이 아니다."""
    assert find_repeating_groups({"satscores": ["enroll12", "cds"]}) == []


def test_code_name_pairs_are_found():
    got = {(c.table, c.code_column, c.name_column) for c in find_code_name_pairs(BIRD)}
    assert ("schools", "soc", "soctype") in got
    assert ("schools", "doc", "doctype") in got
    assert ("schools", "edopscode", "edopsname") in got
    assert ("frpm", "County Name", "County Name") not in got  # 자기 자신과 짝지으면 안 된다


def test_code_name_pairs_handle_spaced_names():
    got = {(c.code_column, c.name_column) for c in find_code_name_pairs(
        {"frpm": ["County Code", "County Name", "District Code", "District Name"]})}
    assert ("County Code", "County Name") in got
    assert ("District Code", "District Name") in got


def test_unrelated_columns_are_not_paired():
    assert find_code_name_pairs({"t": ["price", "quantity", "created_at"]}) == []


def test_duplicate_concepts_span_tables():
    got = {c.concept: {f"{t}.{col}" for t, col in c.columns} for c in find_duplicate_concepts(BIRD)}
    assert got["school"] == {"schools.school", "frpm.School Name"}
    assert got["county"] == {"schools.county", "frpm.County Name"}


def test_single_table_concept_is_not_duplicate():
    """한 테이블 안에만 있으면 중복이 아니다 — 조인 선택의 여지가 없다."""
    assert find_duplicate_concepts({"t": ["school", "school name"]}) == []


def test_concept_aliases_can_bridge_unrelated_names():
    """`satscores.sname`은 이름만으로는 school과 묶이지 않는다 — 별칭으로 연결한다."""
    got = find_duplicate_concepts(
        {"schools": ["school"], "satscores": ["sname"]}, aliases={"sname": "school"})
    assert got and {f"{t}.{c}" for t, c in got[0].columns} == {"schools.school", "satscores.sname"}


# ── 이름이 같아도 개념이 같지 않은 컬럼 ────────────────────────────────────
# 다른 스키마에서 검증하다 드러난 오탐(2026-09-04): `card_games`의 6개 테이블에 있는
# `id`, `financial`의 3개 테이블에 있는 `date`(계좌개설일/거래일/대출일),
# `formula_1`의 4개 테이블에 있는 `time`(경기 시각/완주 기록/랩 타임/피트인 시각).
# 값 검증만으로는 "사본인데 심하게 갈렸다"와 구분되지 않아 이름 단계에서 걸러야 한다.

def test_generic_columns_are_not_duplicate_concepts():
    for col in ("id", "date", "time", "type", "code", "status", "value"):
        got = find_duplicate_concepts({"a": [col, "x"], "b": [col, "y"]})
        assert got == [], f"{col} 이(가) 중복 개념으로 잡혔다"


def test_meaningful_columns_are_still_grouped():
    """제외 목록이 과하면 진짜 중복을 놓친다 — school은 그대로 잡혀야 한다."""
    got = find_duplicate_concepts({"schools": ["school"], "frpm": ["School Name"]})
    assert got and got[0].concept == "school"


def test_qualified_date_columns_are_not_excluded():
    """`date` 자체는 제외하지만 `open_date`처럼 뜻이 붙은 것은 살린다."""
    got = find_duplicate_concepts({"a": ["open_date"], "b": ["open_date"]})
    assert got and got[0].concept == "opendate"
