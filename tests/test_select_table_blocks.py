"""스키마 컨텍스트의 LLM 테이블 선택 (2026-10-15)."""
import asyncio
from types import SimpleNamespace

from pgxnl.agent.orchestrator import Orchestrator
from pgxnl.llm.base import LLMResponse


class _LLM:
    def __init__(self, text=None, exc=None):
        self.text, self.exc = text, exc

    async def complete(self, system_prompt, messages, tools=None):
        if self.exc:
            raise self.exc
        return LLMResponse(text=self.text, tool_calls=[], stop_reason="end_turn")


def _run(llm):
    stub = SimpleNamespace(_llm_overrides={}, _llm_for=lambda stage: llm)
    cands = [SimpleNamespace(table=t) for t in ("posts", "votes", "users", "tags")]
    blocks = ["B-posts", "B-votes", "B-users", "B-tags"]
    logs = []

    async def dbg(m):
        logs.append(m)

    out = asyncio.run(Orchestrator._select_table_blocks(stub, "q", cands, blocks, dbg))
    return out, logs


def test_keeps_only_selected_tables_in_candidate_order():
    out, logs = _run(_LLM('{"tables": ["users", "posts"], "joins": [], "reason": "r"}'))
    assert out == ["B-posts", "B-users"] and "이유: r" in logs[0]


def test_falls_back_to_all_on_failure_or_empty():
    assert _run(_LLM(exc=RuntimeError("down")))[0] == ["B-posts", "B-votes", "B-users", "B-tags"]
    assert _run(_LLM('{"tables": []}'))[0] == ["B-posts", "B-votes", "B-users", "B-tags"]
