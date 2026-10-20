"""컬럼 존재 검증 테스트 (`SqlValidator._bind_columns`).

배경(실측 run 103): `_bind_catalog`가 테이블만 봐서 존재하지 않는 컬럼이 검증을 통과해
실행 단계에서야 `column t1.charternum does not exist`로 터졌다. `AliasFixRule`은 "별칭만
틀린" 경우를 사후 교정할 뿐, 아예 없는 컬럼명은 아무도 잡지 못했다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from pgxnl.agent.validation import Decision, SqlValidator
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

SCHEMA = {
    "schools": ["cdscode", "school", "street", "city", "charternum", "doc"],
    "frpm": ["cdscode", "School Name", "Enrollment (K-12)"],
}


@dataclass
class Col:
    name: str


@dataclass
class Tbl:
    name: str
    columns: list


class FakeConn:
    """describe_table/list_tables만 흉내낸다 — 검증 로직이 대상 DB를 어떻게 쓰는지가 검사 대상."""

    def __init__(self) -> None:
        self.describe_calls: list[str] = []

    async def list_tables(self, schema: str):
        return [Tbl(name=t, columns=[]) for t in SCHEMA]

    async def describe_table(self, schema: str, table: str):
        self.describe_calls.append(table)
        if table not in SCHEMA:
            raise ValueError(f"no such table: {table}")
        return Tbl(name=table, columns=[Col(name=c) for c in SCHEMA[table]])

    async def explain(self, *a, **kw):
        # PgConnector.explain()과 같은 모양 — validation._estimate_cost가 result["plan"]을 읽는다
        return {"plan": {"Total Cost": 1.0}}


class FakeCache:
    def __init__(self) -> None:
        self._d: dict = {}

    async def get(self, target, key):
        return self._d.get(key)

    async def set(self, target, key, data):
        self._d[key] = data


@pytest.fixture
def validator():
    return SqlValidator(
        AntlrPostgresParser(), FakeConn(), None,
        max_cost=1e9, target_name="T", schema_cache=FakeCache(), default_schema="public",
    )


async def decide(validator, sql: str):
    return await validator.validate(sql, user_id=1)


@pytest.mark.asyncio
async def test_nonexistent_column_is_rejected(validator):
    r = await decide(validator, "SELECT T1.charternum FROM frpm T1 JOIN schools T2 ON T1.cdscode = T2.cdscode")
    assert r.decision is Decision.REJECTED
    assert "존재하지 않는 컬럼" in r.reason
    assert "charternum" in r.reason


@pytest.mark.asyncio
async def test_existing_column_passes(validator):
    r = await decide(validator, "SELECT T2.charternum FROM frpm T1 JOIN schools T2 ON T1.cdscode = T2.cdscode")
    assert r.decision is Decision.ALLOWED


@pytest.mark.asyncio
async def test_quoted_column_with_space(validator):
    ok = await decide(validator, 'SELECT T1."School Name" FROM frpm T1')
    bad = await decide(validator, 'SELECT T1."No Such Column" FROM frpm T1')
    assert ok.decision is Decision.ALLOWED
    assert bad.decision is Decision.REJECTED


@pytest.mark.asyncio
async def test_unqualified_columns_are_not_judged(validator):
    """한정하지 않은 컬럼은 어느 테이블 것인지 스코프 분석이 필요하다 — 판단하지 않는다."""
    assert (await decide(validator, "SELECT nonexistent FROM schools")).decision is Decision.ALLOWED


@pytest.mark.asyncio
async def test_star_is_ignored(validator):
    assert (await decide(validator, "SELECT T1.* FROM schools T1")).decision is Decision.ALLOWED


@pytest.mark.asyncio
async def test_subquery_is_skipped(validator):
    """alias_to_table이 스코프를 구분하지 못하므로 서브쿼리가 있으면 판단하지 않는다."""
    sql = "SELECT T1.charternum FROM frpm T1 WHERE T1.cdscode IN (SELECT cdscode FROM schools)"
    assert (await decide(validator, sql)).decision is Decision.ALLOWED


@pytest.mark.asyncio
async def test_where_clause_column_is_checked(validator):
    sql = "SELECT T2.school FROM frpm T1 JOIN schools T2 ON T1.cdscode = T2.cdscode WHERE T1.charternum = '1'"
    r = await decide(validator, sql)
    assert r.decision is Decision.REJECTED


@pytest.mark.asyncio
async def test_column_list_is_cached(validator):
    """같은 테이블을 여러 번 참조해도 describe_table은 한 번만 부른다."""
    sql = "SELECT T1.school, T1.street, T1.city FROM schools T1"
    await decide(validator, sql)
    assert validator._conn.describe_calls.count("schools") == 1


@pytest.mark.asyncio
async def test_describe_failure_does_not_reject(validator):
    """컬럼 목록을 못 가져오면 '판단 불가'이지 거부 사유가 아니다(설계 원칙 1).

    테이블 목록은 정상이고 describe_table만 실패하는 상황 — 그래야 테이블 검증을
    통과한 뒤 컬럼 검증에서 판단 불가가 되는 경로를 탄다.
    """
    async def boom(schema, table):
        raise TimeoutError

    validator._conn.describe_table = boom
    assert (await decide(validator, "SELECT T1.whatever FROM schools T1")).decision is Decision.ALLOWED


@pytest.mark.asyncio
async def test_no_schema_cache_skips_the_check():
    v = SqlValidator(
        AntlrPostgresParser(), FakeConn(), None,
        max_cost=1e9, target_name="T", schema_cache=None, default_schema="public",
    )
    assert (await v.validate("SELECT T1.nope FROM schools T1", user_id=1)).decision is Decision.ALLOWED
