"""등록 시점 카탈로그 대조 테스트 (`glossary_terms.verify_against_catalog`).

배경(실측 2026-09-03): 관리자가 `table_name='shcools'`(오타)로 등록했는데 경고가 없었다.
`for_table()`은 `table_name='schools'`로 조회하므로 그 항목은 **어떤 질문에도 실리지
않는 상태**로 등록됐다. `diagnose()`는 순수 함수라 텍스트만 봐서 이걸 못 잡는다 —
등록 시점 진단의 목적이 정확히 "등록은 됐는데 효과가 없는 상태"를 막는 것인데 뚫렸다.
"""
from __future__ import annotations

import pytest

from pgxnl.governance.glossary_terms import verify_against_catalog

SCHEMA = {"schools": {"cdscode", "school", "county", "soc"},
          "frpm": {"cdscode", "School Name", "Enrollment (K-12)"}}
KNOWN = set(SCHEMA)


async def lookup(schema: str, table: str) -> set[str] | None:
    return SCHEMA.get(table)


async def verify(**kw):
    kw.setdefault("target_name", "BIRD")
    kw.setdefault("schema_name", "california_schools")
    kw.setdefault("column_name", None)
    return await verify_against_catalog(lookup, known_tables=KNOWN, **kw)


@pytest.mark.asyncio
async def test_typo_in_table_name_is_caught_with_a_suggestion():
    w = await verify(table_name="shcools", column_name="school")
    assert w and "'shcools' 테이블이 없습니다" in w[0]
    assert "'schools'" in w[0]  # 가까운 이름을 제안해야 고치기 쉽다


@pytest.mark.asyncio
async def test_missing_column_is_caught_with_a_suggestion():
    w = await verify(table_name="schools", column_name="scohol")
    assert w and "'scohol' 컬럼이 없습니다" in w[0]
    assert "'school'" in w[0]


@pytest.mark.asyncio
async def test_existing_table_and_column_pass():
    assert await verify(table_name="schools", column_name="school") == []
    assert await verify(table_name="frpm", column_name="School Name") == []


@pytest.mark.asyncio
async def test_column_match_is_case_insensitive():
    """카탈로그는 'School Name', 등록은 'school name'일 수 있다."""
    assert await verify(table_name="frpm", column_name="school name") == []


@pytest.mark.asyncio
async def test_table_without_column_is_still_checked():
    assert await verify(table_name="schools") == []
    assert await verify(table_name="nope") != []


@pytest.mark.parametrize("missing", ["target_name", "schema_name", "table_name"])
@pytest.mark.asyncio
async def test_null_scope_fields_skip_verification(missing):
    """NULL은 '제한 없음'을 뜻하는 관례다 — 특정 DB로 판정하면 안 된다."""
    kw = {"target_name": "BIRD", "schema_name": "california_schools",
          "table_name": "shcools", "column_name": "school", missing: None}
    assert await verify_against_catalog(lookup, known_tables=KNOWN, **kw) == []


@pytest.mark.asyncio
async def test_lookup_failure_does_not_warn():
    """대상 DB에 못 붙는 것은 '판단 불가'이지 등록을 막을 사유가 아니다."""
    async def boom(schema, table):
        raise TimeoutError

    assert await verify_against_catalog(
        boom, target_name="BIRD", schema_name="s", table_name="t", column_name="c",
    ) == []


@pytest.mark.asyncio
async def test_no_suggestion_when_nothing_is_close():
    w = await verify(table_name="completely_unrelated_name")
    assert w and "의도하셨나요" not in w[0]
