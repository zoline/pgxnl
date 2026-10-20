"""예시 쌍 기반 뒤쪽 재작성 단계 — 특히 '무엇을 거절하는가'."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonical_rewrite import (
    RewriteExample, build_prompt, extract_sql, load_examples, rewrite_sql, verify_rewrite,
)
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


ORIG = "SELECT COUNT(*) AS c, T1.city, COUNT(*) AS n FROM schools AS T1 WHERE T1.magnet = 1 AND T1.city = 'Adelanto' GROUP BY T1.city"


# ---- 정의 로딩 ----

def test_쌍이_아니면_예시가_아니다() -> None:
    assert load_examples([{"bad_sql": "SELECT 1"}]) == []
    assert load_examples([{"good_sql": "SELECT 1"}]) == []
    assert len(load_examples([{"bad_sql": "SELECT 1, 1", "good_sql": "SELECT 1"}])) == 1


def test_definition이_dict가_아니면_건너뛴다() -> None:
    assert load_examples(["문자열로 들어온 jsonb"]) == []


def test_when_regex로_후보를_거른다() -> None:
    ex = RewriteExample("SELECT 1, 1", "SELECT 1", when_regex=r"GROUP\s+BY")
    assert ex.applies_to("SELECT a FROM t GROUP BY a")
    assert not ex.applies_to("SELECT a FROM t")


def test_잘못된_정규식은_후보에서_빠진다() -> None:
    assert not RewriteExample("a", "b", when_regex="[").applies_to("SELECT 1")


# ---- 응답 파싱 ----

@pytest.mark.parametrize("raw,expected", [
    ("SELECT 1", "SELECT 1"),
    ("```sql\nSELECT 1\n```", "SELECT 1"),
    ("```\nSELECT 1\n```", "SELECT 1"),
    ("SELECT 1;", "SELECT 1"),
    ("", ""),
])
def test_응답에서_sql만_꺼낸다(raw: str, expected: str) -> None:
    assert extract_sql(raw) == expected


# ---- 검증: 받아들이는 것 ----

def test_컬럼만_줄이면_받아들인다(parser: AntlrPostgresParser) -> None:
    good = "SELECT T1.city, COUNT(*) AS n FROM schools AS T1 WHERE T1.magnet = 1 AND T1.city = 'Adelanto' GROUP BY T1.city"
    ok, reason = verify_rewrite(ORIG, good, parser)
    assert ok, reason


def test_컬럼_순서만_바꿔도_받아들인다(parser: AntlrPostgresParser) -> None:
    orig = "SELECT a, b FROM t WHERE c = 1"
    ok, reason = verify_rewrite(orig, "SELECT b, a FROM t WHERE c = 1", parser)
    assert ok, reason


# ---- 검증: 거절하는 것 ----

def test_필터_값을_바꾸면_거절한다(parser: AntlrPostgresParser) -> None:
    bad = "SELECT T1.city, COUNT(*) AS n FROM schools AS T1 WHERE T1.magnet = 1 AND T1.city = 'Fresno' GROUP BY T1.city"
    ok, reason = verify_rewrite(ORIG, bad, parser)
    assert not ok and "거르는 값" in reason


def test_필터_값의_순서를_뒤바꾸면_거절한다(parser: AntlrPostgresParser) -> None:
    # 집합으로 비교하면 통과해버리는 변조 — 값은 그대로인데 의미가 뒤집힌다.
    orig = "SELECT a FROM t WHERE city = 'A' AND county = 'B'"
    swapped = "SELECT a FROM t WHERE city = 'B' AND county = 'A'"
    ok, reason = verify_rewrite(orig, swapped, parser)
    assert not ok and "거르는 값" in reason


def test_테이블을_바꾸면_거절한다(parser: AntlrPostgresParser) -> None:
    ok, reason = verify_rewrite("SELECT a FROM t WHERE c = 1", "SELECT a FROM u WHERE c = 1", parser)
    assert not ok and "참조 테이블" in reason


def test_조건을_추가하면_거절한다(parser: AntlrPostgresParser) -> None:
    ok, reason = verify_rewrite("SELECT a FROM t WHERE c = 1", "SELECT a FROM t WHERE c = 1 AND d = 2", parser)
    assert not ok and "거르는 값" in reason


def test_문법이_깨지면_거절한다(parser: AntlrPostgresParser) -> None:
    ok, reason = verify_rewrite("SELECT a FROM t", "SELECT FROM WHERE", parser)
    assert not ok and "문법" in reason


def test_select가_아니면_거절한다(parser: AntlrPostgresParser) -> None:
    ok, reason = verify_rewrite("SELECT a FROM t", "DELETE FROM t", parser)
    assert not ok


def test_변경이_없으면_적용하지_않는다(parser: AntlrPostgresParser) -> None:
    ok, reason = verify_rewrite("SELECT a FROM t", "SELECT a FROM t", parser)
    assert not ok and reason == "변경 없음"


def test_빈_응답은_거절한다(parser: AntlrPostgresParser) -> None:
    ok, reason = verify_rewrite("SELECT a FROM t", "", parser)
    assert not ok and reason == "빈 응답"


# ---- 호출 경로 ----

class _StubLLM:
    def __init__(self, text: str) -> None:
        self.text_out, self.calls = text, 0

    async def complete(self, **kwargs):
        self.calls += 1
        class _R:
            text = self.text_out
        return _R()


@pytest.mark.asyncio
async def test_해당_예시가_없으면_llm을_부르지_않는다(parser: AntlrPostgresParser) -> None:
    llm = _StubLLM("SELECT 1")
    ex = [RewriteExample("a", "b", when_regex=r"GROUP\s+BY")]
    out, reason = await rewrite_sql("SELECT a FROM t", ex, llm, parser)
    assert out == "SELECT a FROM t" and llm.calls == 0
    assert "호출 안 함" in reason


@pytest.mark.asyncio
async def test_검증에_걸리면_원본을_돌려준다(parser: AntlrPostgresParser) -> None:
    llm = _StubLLM("SELECT a FROM 다른테이블 WHERE c = 1")
    out, reason = await rewrite_sql(
        "SELECT a FROM t WHERE c = 1", [RewriteExample("x", "y")], llm, parser,
    )
    assert out == "SELECT a FROM t WHERE c = 1" and llm.calls == 1


@pytest.mark.asyncio
async def test_llm이_던져도_원본으로_이어간다(parser: AntlrPostgresParser) -> None:
    class _Boom:
        async def complete(self, **kwargs):
            raise RuntimeError("서버 없음")
    out, reason = await rewrite_sql("SELECT a FROM t", [RewriteExample("x", "y")], _Boom(), parser)
    assert out == "SELECT a FROM t" and "호출 실패" in reason


def test_프롬프트에_예시가_들어간다() -> None:
    p = build_prompt([RewriteExample("SELECT 1, 1", "SELECT 1", explanation="중복 제거")])
    assert "SELECT 1, 1" in p and "중복 제거" in p


# ---- 코드 폴백: LLM이 수용되는 변경을 못 내면 파서가 확정한다 ----

_DUP = ("SELECT COUNT(*) AS c, T1.city, COUNT(*) AS n FROM schools AS T1 "
        "WHERE T1.magnet = 1 GROUP BY T1.city")
_WITH_KIND = RewriteExample("SELECT 1, 1", "SELECT 1", kind="dedupe_columns")


def test_kind를_정의에서_읽는다() -> None:
    ex = load_examples([{"bad_sql": "a", "good_sql": "b", "kind": "dedupe_columns"}])
    assert ex[0].kind == "dedupe_columns"


@pytest.mark.asyncio
async def test_llm이_무변경이면_폴백이_돈다(parser: AntlrPostgresParser) -> None:
    llm = _StubLLM(_DUP)  # 받은 그대로 돌려줌 = 변경 없음
    out, reason = await rewrite_sql(_DUP, [_WITH_KIND], llm, parser)
    assert out.startswith("SELECT T1.city, COUNT(*) AS n FROM")
    assert "폴백" in reason and "변경 없음" in reason


@pytest.mark.asyncio
async def test_llm이_터져도_폴백이_돈다(parser: AntlrPostgresParser) -> None:
    class _Boom:
        async def complete(self, **kwargs):
            raise RuntimeError("서버 없음")
    out, reason = await rewrite_sql(_DUP, [_WITH_KIND], _Boom(), parser)
    assert out.startswith("SELECT T1.city, COUNT(*) AS n FROM")
    assert "폴백" in reason


@pytest.mark.asyncio
async def test_불변식에_걸려도_폴백이_돈다(parser: AntlrPostgresParser) -> None:
    llm = _StubLLM("SELECT T1.city FROM 다른테이블 AS T1 WHERE T1.magnet = 1 GROUP BY T1.city")
    out, reason = await rewrite_sql(_DUP, [_WITH_KIND], llm, parser)
    assert "다른테이블" not in out
    assert out.startswith("SELECT T1.city, COUNT(*) AS n FROM")
    assert "폴백" in reason


@pytest.mark.asyncio
async def test_llm이_해내면_폴백은_돌지_않는다(parser: AntlrPostgresParser) -> None:
    good = "SELECT T1.city, COUNT(*) FROM schools AS T1 WHERE T1.magnet = 1 GROUP BY T1.city"
    out, reason = await rewrite_sql(_DUP, [_WITH_KIND], _StubLLM(good), parser)
    assert out == good and reason.startswith("LLM 수용")


@pytest.mark.asyncio
async def test_kind가_없으면_폴백_없이_원본(parser: AntlrPostgresParser) -> None:
    out, reason = await rewrite_sql(_DUP, [RewriteExample("a", "b")], _StubLLM(_DUP), parser)
    assert out == _DUP and "폴백 없음" in reason


@pytest.mark.asyncio
async def test_모르는_kind는_폴백이_없다(parser: AntlrPostgresParser) -> None:
    ex = RewriteExample("a", "b", kind="존재하지_않는_규칙")
    out, reason = await rewrite_sql(_DUP, [ex], _StubLLM(_DUP), parser)
    assert out == _DUP and "폴백 없음" in reason
