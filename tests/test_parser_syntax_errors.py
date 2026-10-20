"""문법 오류 처리 테스트 (`AntlrPostgresParser`, `SqlValidator`, `canonicalize_sql`).

배경(실측 2026-09-03, run 166): 평가 로그에 `line 5:0 mismatched input 'HAVING'
expecting <EOF>`가 찍혔는데 평가는 그대로 완료됐다. `_build_tree`가 ANTLR 기본
콘솔 리스너를 떼지 않고 `getNumberOfSyntaxErrors()`도 보지 않아, 오류가 stderr로만
나가고 **복구된 불완전한 트리가 정상인 것처럼 반환**되고 있었다.

이게 로그 노이즈에 그치지 않는 이유: PG는 받아들이는데 우리 문법이 지원 못 하는
구문에서 `referenced_tables`가 조용히 누락되면, 검증 계층의 카탈로그/컬럼/PII 검사가
"볼 수 없었던 것"을 "문제 없음"으로 통과시킨다 — 문법 커버리지 구멍이 그대로
거버넌스 구멍이 된다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import EnsureLimitRule, canonicalize_sql
from pgxnl.agent.validation import Decision, SqlValidator
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

# 문장이 끝난 뒤 잔여물이 붙은 형태 — ANTLR이 앞부분만 살리고 뒤를 버린다
TRAILING_JUNK = "SELECT a FROM schools LIMIT 1 HAVING COUNT(*) > 5"
UNCLOSED_PAREN = "SELECT count(* FROM schools"


@pytest.fixture
def parser():
    return AntlrPostgresParser()


@pytest.mark.parametrize("sql", [TRAILING_JUNK, UNCLOSED_PAREN])
def test_syntax_errors_are_reported(parser, sql):
    stmt = parser.parse(sql)
    assert not stmt.is_well_formed
    assert stmt.syntax_errors


@pytest.mark.parametrize("sql", [
    "SELECT a FROM schools WHERE b = 1",
    "SELECT city, COUNT(*) FROM schools GROUP BY city HAVING COUNT(*) > 5",
    "SELECT city FROM schools GROUP BY city HAVING COUNT(*) > 5 ORDER BY city",
    'SELECT T1."School Name" FROM frpm T1 JOIN schools T2 ON T1.cdscode = T2.cdscode',
    "SELECT x, RANK() OVER (PARTITION BY y ORDER BY z DESC NULLS LAST) FROM t",
    "WITH c AS (SELECT 1 AS n) SELECT n FROM c",
])
def test_valid_sql_has_no_syntax_errors(parser, sql):
    """정상 SQL이 오류로 잡히면 안 된다 — 이 검사가 곧 문법 커버리지 회귀 테스트다."""
    stmt = parser.parse(sql)
    assert stmt.is_well_formed, stmt.syntax_errors


def test_nothing_is_printed_to_console(parser, capfd):
    """ANTLR 기본 리스너가 stderr로 직접 찍던 것을 없앴다 — SQL이 콘솔로 새면 안 된다."""
    parser.parse(TRAILING_JUNK)
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_canonicalize_leaves_broken_sql_untouched(parser):
    """깨진 트리의 토큰 인덱스로 원문을 재작성하면 엉뚱한 위치를 건드린다."""
    assert canonicalize_sql(UNCLOSED_PAREN, parser, [EnsureLimitRule(100)]) == UNCLOSED_PAREN


@pytest.mark.asyncio
async def test_validator_rejects_unparseable_sql(parser):
    """바인딩을 신뢰할 수 없으면 통과가 아니라 거부다 — 검증은 보안 게이트다."""
    v = SqlValidator(parser, None, None, max_cost=1e9, target_name="T", schema_cache=None)
    r = await v.validate(TRAILING_JUNK, user_id=1)
    assert r.decision is Decision.REJECTED
    assert "구문을 해석할 수 없습니다" in r.reason


# ── generate_sql의 문법 검증이 죽어 있던 문제 ──────────────────────────────
# `parser.parse(sql)`이 문법 오류에 예외를 던지지 않으므로, 예외만 잡던 재시도
# 루프는 한 번도 발동하지 않았다 — 깨진 SQL이 그대로 통과했다.

from dataclasses import dataclass

from pgxnl.agent.tools.generate_sql import SqlGenerationError, generate_sql


@dataclass
class _Resp:
    text: str


class _ScriptedLLM:
    """정해진 순서대로 응답을 돌려주고, 받은 프롬프트를 기록한다."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    async def complete(self, *, system_prompt: str, messages):
        self.prompts.append(system_prompt)
        return _Resp(self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)])


@pytest.mark.asyncio
async def test_broken_sql_triggers_a_retry(parser):
    llm = _ScriptedLLM([UNCLOSED_PAREN, "SELECT a FROM schools"])
    sql = await generate_sql(llm, parser, "q", "schema", max_corrections=2)
    assert sql == "SELECT a FROM schools"
    assert len(llm.prompts) == 2
    assert "구문 오류" in llm.prompts[1]  # 오류 내용이 재작성 힌트로 돌아간다


@pytest.mark.asyncio
async def test_valid_sql_returns_on_first_try(parser):
    llm = _ScriptedLLM(["SELECT a FROM schools"])
    assert await generate_sql(llm, parser, "q", "schema", max_corrections=2) == "SELECT a FROM schools"
    assert len(llm.prompts) == 1


@pytest.mark.asyncio
async def test_persistently_broken_sql_raises(parser):
    llm = _ScriptedLLM([UNCLOSED_PAREN])
    with pytest.raises(SqlGenerationError):
        await generate_sql(llm, parser, "q", "schema", max_corrections=1)


# ── 코드펜스 제거 ──────────────────────────────────────────────────────────
# `.strip("```sql")`의 인자는 부분문자열이 아니라 **문자 집합**이다 — 펜스 없이
# SQL만 돌아오면 끝의 s/q/l/백틱이 잘려나갔다.

from pgxnl.agent.tools.generate_sql import strip_code_fence


@pytest.mark.parametrize("raw,expected", [
    ("SELECT * FROM schools", "SELECT * FROM schools"),          # 예전엔 'schoo'가 됐다
    ("SELECT q FROM tbl", "SELECT q FROM tbl"),                  # 예전엔 'tb'가 됐다
    ("```sql\nSELECT * FROM schools\n```", "SELECT * FROM schools"),
    ("```\nSELECT a FROM t\n```", "SELECT a FROM t"),
    ("  ```sql SELECT a FROM t ```  ", "SELECT a FROM t"),
    ("```postgresql\nSELECT 1\n```", "SELECT 1"),
    ("SELECT a FROM t WHERE x LIKE '%sql%'", "SELECT a FROM t WHERE x LIKE '%sql%'"),
    ("", ""),
])
def test_strip_code_fence(raw, expected):
    assert strip_code_fence(raw) == expected


def test_fence_stripping_does_not_corrupt_identifiers(parser):
    """실제 경로 확인 — 잘린 테이블명은 '존재하지 않는 테이블' 오류로 이어졌다."""
    stmt = parser.parse(strip_code_fence("SELECT cdscode FROM california_schools.schools"))
    assert stmt.referenced_tables == ["california_schools.schools"]
