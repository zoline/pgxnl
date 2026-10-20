"""용어집 관련성 필터 테스트 (`orchestrator._glossary_relevant`).

배경(실측 2026-09-03): 예전 필터는 정의문에 "코드=값" 나열이 없으면 무조건 통과시켜
13개 항목 중 10개가 30문항 전부에서 실렸다 — schema_context의 43%(1,761자)가 매 질문마다
무관한 용어집이었다. 기본값을 "제외"로 뒤집고, 질문에 문자 그대로 등장하는 단서만 본다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.orchestrator import _glossary_relevant
from pgxnl.governance.glossary import GlossaryEntry
from pgxnl.governance.glossary_terms import (
    definition_values as _definition_values,
    diagnose,
    mentions as _mentions,
    normalize_definition,
)


def entry(term: str, definition: str, column: str | None = None) -> GlossaryEntry:
    return GlossaryEntry(
        id=1, term=term, table_name="schools", column_name=column,
        definition=definition, is_pii=False,
    )


DOC = entry(
    "DOC, District Ownership Code",
    "Values: 00=County Office of Education, 31=State Special Schools, "
    "54=Unified School District, 98=Regional Occupational Center/Program",
    column="doc",
)
FUNDING = entry(
    "FundingType, charter school funding type",
    "Values: Not in CS funding model, Locally funded, Directly funded",
    column="fundingtype",
)
MAGNET = entry("Magnet, magnet school", "Integer 0/1 in this database. 1 = magnet school.", column="magnet")


def test_unrelated_question_excludes_entry():
    """예전 구현의 핵심 결함 — 서술형 정의가 무조건 통과하던 것을 뒤집었다."""
    assert not _glossary_relevant("How many schools are in Fresno county?", MAGNET)
    assert not _glossary_relevant("What is the highest SAT reading score?", FUNDING)


def test_alias_match():
    assert _glossary_relevant("List the names and DOC type of schools", DOC)
    assert _glossary_relevant("schools that offer a magnet program", MAGNET)


def test_alias_alternatives_are_comma_separated():
    """term에 쉼표로 나열한 표현은 각각이 별칭이다 — 하나만 맞아도 실린다."""
    e = entry("GSoffered, grade span offered", "Lowest-to-highest grade span the institution offers.")
    assert _glossary_relevant("What grade span is offered by the school?", e)
    assert _glossary_relevant("What is the GSoffered value?", e)


def test_alias_ignores_word_order():
    e = entry("average score in writing, average writing score", "Per-school average SAT writing score.")
    assert _glossary_relevant("Rank schools by their average writing score", e)


def test_value_label_match_without_code():
    """seq 447: 정의가 값만 나열해 코드=값 쌍이 없었고, 질문의 'locally funded'를
    아무 신호도 잡지 못했다."""
    assert _glossary_relevant("list schools that are locally funded", FUNDING)


def test_value_label_match_with_code():
    assert _glossary_relevant("Which state special schools have the most enrollees?", DOC)


def test_bare_code_is_not_a_signal():
    """seq 452: 날짜 12/31/1980이 DOC의 코드 '31'에 걸려 무관한 항목이 실렸다."""
    q = "average number of test takers from Fresno schools that opened between 1/1/1980 and 12/31/1980"
    assert not _glossary_relevant(q, DOC)


def test_partial_word_does_not_match():
    """'DOC'가 'document'/'doctor' 안에 부분 일치하면 안 된다."""
    assert not _glossary_relevant("How many documents mention the doctor?", DOC)


def test_values_are_not_split_on_slash():
    """seq 465: 'Regional Occupational Center/Program'이 'Program'으로 쪼개져
    "magnet program"에 걸렸다 — 값 라벨의 일부는 그 값을 가리키지 않는다."""
    assert "Program" not in _definition_values(DOC.definition)
    assert not _glossary_relevant("schools that offer a magnet program", DOC)


def test_code_prefix_is_stripped_from_listed_values():
    assert "State Special School" in _definition_values("Values: ALTSOC, SSS=State Special School, TRAD")


def test_short_values_are_ignored():
    """두세 글자 값은 우연히 일치하기 쉬워 신호로 쓰지 않는다."""
    assert _definition_values("Values: F=Yes, N=No") == []


def test_mentions_requires_every_token():
    assert _mentions("unified school district in orange county", "Unified School District")
    assert not _mentions("unified district", "Unified School District")


def test_entry_without_column_name_still_matches_on_term():
    assert _glossary_relevant("what is the operating status?", entry("operating status", "Values: Active, Closed"))


# ── 등록 시점 정규화/진단 ──────────────────────────────────────────────────
# 필터를 "기본 제외"로 뒤집으면서 생긴 실패 모드: 서술형으로 등록하면 조용히 한 번도
# 안 실린다. 등록 시점에 같은 규칙으로 진단해 그 자리에서 알려준다.


def test_normalize_unifies_slash_separated_values():
    """실제로 FundingType이 `"A" / "B" / "C"` 형태로 등록돼 있었다."""
    out = normalize_definition('values: "Not in CS funding model" / "Locally funded" / "Directly funded"')
    assert out == "values: Not in CS funding model, Locally funded, Directly funded"
    assert _mentions("schools that are locally funded", _definition_values(out)[1])


def test_normalize_keeps_slash_inside_a_value():
    """쉼표로 이미 나뉜 나열은 건드리지 않는다 — `Center/Program`을 쪼개면 안 된다."""
    out = normalize_definition("Values: 00=County Office of Education, 98=Regional Occupational Center/Program")
    assert "Regional Occupational Center/Program" in _definition_values(out)


def test_normalize_collapses_whitespace_and_korean_label():
    assert normalize_definition("값:  Active,\n  Closed ") == "Values: Active, Closed"


def test_normalize_is_idempotent():
    once = normalize_definition('값: "A one" / "B two"')
    assert normalize_definition(once) == once


def test_diagnose_flags_a_dead_entry():
    d = diagnose("", None, "설명만 있고 값 나열도 등록어도 없다.")
    assert d.is_dead
    assert d.warnings


def test_diagnose_flags_prose_definition_without_values():
    d = diagnose("Magnet", "magnet", "Whether the school is a magnet school, described as Y/N in the docs.")
    assert not d.is_dead
    assert any("Values:" in w for w in d.warnings)


def test_diagnose_flags_single_word_term():
    d = diagnose("GSoffered", "gsoffered", "Lowest-to-highest grade span offered.")
    assert any("자연어" in w for w in d.warnings)


def test_diagnose_flags_long_definition():
    d = diagnose("SOC, school ownership code", "soc", "Values: " + ", ".join(f"{i}=Value Number {i}" for i in range(40)))
    assert any("깁니다" in w for w in d.warnings)


def test_a_well_formed_entry_has_no_warnings():
    d = diagnose(
        "FundingType, charter school funding type", "fundingtype",
        "Values: Not in CS funding model, Locally funded, Directly funded",
    )
    assert d.warnings == []
    assert "Locally funded" in d.values
    assert "charter school funding type" in d.aliases


def test_normalize_preserves_label_casing_inside_a_sentence():
    """소문자 `values:`를 `Values:`로 고치면 "the text values:" 같은 문장 중간의
    낱말까지 바뀌어 문장이 망가진다 — 라벨 표기는 원문 그대로 둔다."""
    assert normalize_definition("Education Option Code — text values: ALTSOC, COMM") == (
        "Education Option Code — text values: ALTSOC, COMM"
    )
    assert "Example values:" in normalize_definition("School Type. Example values: A one, B two, etc.")


def test_normalize_fixes_slash_list_without_recasing_the_label():
    assert normalize_definition('Funding Type — values: "Locally funded" / "Directly funded"') == (
        "Funding Type — values: Locally funded, Directly funded"
    )


def test_values_are_found_regardless_of_label_casing():
    """필터는 `values:`/`Values:`/`값:`을 모두 읽는다 — 표기를 강제하지 않는다."""
    for label in ("values", "Values", "VALUES", "값"):
        assert "Locally funded" in _definition_values(f"{label}: Locally funded, Directly funded")


# ── 임계값: 필터는 용어집이 커질 때만 작동한다 ─────────────────────────────
# 항상 거르면 안 된다는 걸 실측으로 확인했다(2026-09-03): 질문당 용어집을
# 1,761자 -> 165자로 줄이자 EX가 19.7 -> 15.0으로 떨어졌고, 깨진 문항들은
# 용어집을 0자 받는 문항이었다. 내용이 아니라 길이 자체가 작용하고 있었다.

from pgxnl.agent.orchestrator import _limit_glossary


def test_small_glossary_is_not_filtered_at_all():
    terms = [DOC, FUNDING, MAGNET]
    assert _limit_glossary(terms, "완전히 무관한 질문", threshold_chars=3000) == terms


def test_large_glossary_falls_back_to_relevance_filtering():
    terms = [DOC, FUNDING, MAGNET]
    kept = _limit_glossary(terms, "list schools that are locally funded", threshold_chars=10)
    assert kept == [FUNDING]


def test_threshold_counts_definition_length_only():
    """등록어 길이는 프롬프트에 실리는 양이 아니다 — 정의문만 센다."""
    long_term = entry("x" * 500, "Values: Locally funded", column="c")
    assert _limit_glossary([long_term], "무관", threshold_chars=100) == [long_term]
