"""윈도우 함수 오용 검사 (`validation.window_misuse_clause`).

배경(실측 BIRD seq 454, 8개 run에서 동일하게 반복): "카운티별 상위 5개"를 모델이
이렇게 쓴다 —

    WHERE T1.virtual = 'F'
      AND RANK() OVER (PARTITION BY T1.county ORDER BY T2.avgscrread DESC) <= 5

문법은 완전히 정상이라 파서도 통과하고, 실행 단계에서야 PG가
`window functions are not allowed in WHERE`로 거부한다. 같은 모델이 대안으로 쓴
`QUALIFY`는 Snowflake/DuckDB 문법이라 PG에 없다.

`_bind_columns`와 같은 계열이다 — 실행하면 반드시 실패하는 SQL을 미리 잡는다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.validation import Decision, SqlValidator, window_misuse_clause
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

SEQ_454_BAD = """
SELECT T1.school
FROM schools T1
JOIN satscores T2 ON T1.cdscode = T2.cds
WHERE T1.virtual = 'F'
  AND RANK() OVER (PARTITION BY T1.county ORDER BY T2.avgscrread DESC NULLS LAST) <= 5
"""

SEQ_454_GOOD = """
SELECT school FROM (
  SELECT T2.school, RANK() OVER (PARTITION BY T2.county ORDER BY T1.avgscrread DESC NULLS LAST) AS rnk
  FROM satscores T1 JOIN schools T2 ON T1.cds = T2.cdscode
  WHERE T2.virtual = 'F'
) AS x WHERE x.rnk <= 5
"""


@pytest.fixture
def parser():
    return AntlrPostgresParser()


@pytest.mark.parametrize("sql,clause", [
    (SEQ_454_BAD, "WHERE"),
    ("SELECT a FROM t GROUP BY a HAVING RANK() OVER (ORDER BY a) <= 3", "HAVING"),
    ("SELECT a FROM t GROUP BY RANK() OVER (ORDER BY a)", "GROUP BY"),
    ("SELECT a FROM t JOIN u ON t.x = RANK() OVER (ORDER BY u.y)", "JOIN ... ON"),
])
def test_forbidden_clauses_are_detected(parser, sql, clause):
    assert window_misuse_clause(parser.parse(sql)) == clause


@pytest.mark.parametrize("sql", [
    SEQ_454_GOOD,                                              # 정답 형태
    "SELECT a, RANK() OVER (ORDER BY b) FROM t WHERE c = 1",   # SELECT는 허용
    "SELECT a FROM t ORDER BY RANK() OVER (ORDER BY a)",       # ORDER BY도 허용
    "SELECT a FROM t WHERE b = 1",                             # 윈도우 함수 없음
    "SELECT s FROM (SELECT s, RANK() OVER (ORDER BY v) r FROM t) x WHERE r <= 5",
])
def test_allowed_usage_is_not_flagged(parser, sql):
    """과잉 차단은 정상 질의를 죽인다 — 서브쿼리 안의 윈도우 함수는 건드리면 안 된다."""
    assert window_misuse_clause(parser.parse(sql)) is None


def test_no_tree_is_not_judged(parser):
    stmt = parser.parse("SELECT 1")
    stmt.raw_tree = None
    assert window_misuse_clause(stmt) is None


@pytest.mark.asyncio
async def test_validator_rejects_with_a_fix_hint(parser):
    v = SqlValidator(parser, None, None, max_cost=1e9, target_name="T", schema_cache=None)
    r = await v.validate(SEQ_454_BAD, user_id=1)
    assert r.decision is Decision.REJECTED
    assert "WHERE 절에는 윈도우 함수" in r.reason
    assert "서브쿼리" in r.reason  # 고치는 방법이 사유에 담겨야 ReAct가 스스로 고친다


@pytest.mark.asyncio
async def test_validator_allows_the_subquery_form(parser):
    v = SqlValidator(parser, None, None, max_cost=1e9, target_name="T", schema_cache=None)
    assert (await v.validate(SEQ_454_GOOD, user_id=1)).decision is Decision.ALLOWED


# ------------------------------------------------- ReAct 루프 상한 (시간 / 잘린 응답)

import asyncio

import pytest

from pgxnl.agent.planner import ReactPlanner
from pgxnl.llm.base import LLMResponse


class _ScriptedLLM:
    """정해진 응답을 순서대로 돌려주는 페이크. 마지막 응답은 계속 반복한다."""

    provider = "fake"

    def __init__(self, responses, delay: float = 0.0):
        self._responses = responses
        self._delay = delay
        self.calls = 0
        self.messages_seen = []

    async def complete(self, system_prompt, messages, tools=None):
        self.calls += 1
        self.messages_seen.append(list(messages))
        if self._delay:
            await asyncio.sleep(self._delay)
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx]

    def format_assistant_message(self, response):
        return {"role": "assistant", "content": response.text or ""}

    def format_tool_results(self, results):
        return {"role": "user", "content": str(results)}


def _truncated():
    return LLMResponse(text="아주 긴 추론...", tool_calls=[], stop_reason="max_tokens")


async def test_truncated_responses_stop_after_limit():
    """출력 상한에 걸려 잘린 응답은 도구 호출이 없어 진전이 없다. 그런데 그 8천 토큰이
    대화에 쌓여 다음 호출을 더 느리고 더 잘리게 만든다 — 실측(BIRD 465): in:30,023 /
    out:8,192 한 번에 452초. 연속 2회면 포기한다."""
    llm = _ScriptedLLM([_truncated()])
    planner = ReactPlanner(llm, [], {}, max_iterations=20)

    with pytest.raises(TimeoutError, match="잘린 것이"):
        await planner.run("sys", "질문")

    assert llm.calls == ReactPlanner.MAX_TRUNCATED_IN_A_ROW  # 20회를 다 돌지 않는다


async def test_truncated_response_pushes_back_a_shorter_answer_request():
    """첫 잘림에는 포기하지 않고 "짧게 답하라"를 돌려준다."""
    llm = _ScriptedLLM([_truncated()])
    planner = ReactPlanner(llm, [], {}, max_iterations=20)

    with pytest.raises(TimeoutError):
        await planner.run("sys", "질문")

    second_call_messages = llm.messages_seen[1]
    assert any("출력 길이 제한에 걸려 잘렸습니다" in str(m.get("content", "")) for m in second_call_messages)


async def test_wall_clock_limit_stops_the_loop():
    """반복 횟수만으로는 상한이 되지 않는다 — 한 반복이 450초면 20회는 2.5시간이다."""
    llm = _ScriptedLLM([LLMResponse(text="", tool_calls=[], stop_reason="other")], delay=0.05)
    planner = ReactPlanner(llm, [], {}, max_iterations=100, max_seconds=0.1)

    with pytest.raises(TimeoutError, match="제한 시간"):
        await planner.run("sys", "질문")

    assert llm.calls < 100


async def test_no_time_limit_when_max_seconds_is_none():
    llm = _ScriptedLLM([LLMResponse(text="답", tool_calls=[], stop_reason="end_turn")])
    planner = ReactPlanner(llm, [], {}, max_iterations=5, max_seconds=None)

    assert await planner.run("sys", "질문") == "답"
