"""LLM 클라이언트 공통 인터페이스.

design 문서 §5.6 참고. Anthropic/OpenAI 호환(vLLM, Ollama) 클라이언트 간
메시지 히스토리 포맷 차이를 이 인터페이스 뒤로 숨긴다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    stop_reason: str  # 'tool_use' | 'end_turn' | 'max_tokens' 등으로 정규화
    # {"input_tokens": int, "output_tokens": int} — 공급자가 안 주면 None(디버그 표시에서만
    # 생략, 나머지 로직은 이 필드에 의존하지 않는다).
    usage: dict[str, int] | None = None


class BaseLLMClient(ABC):
    provider: str

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    def format_assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        """LLMResponse를 각 공급자의 메시지 히스토리 포맷으로 변환."""

    @abstractmethod
    def format_tool_results(self, results: list[tuple[ToolCall, Any]]) -> dict[str, Any]:
        """도구 실행 결과를 각 공급자의 tool_result 포맷으로 변환.

        Anthropic: content 블록 내 tool_result / OpenAI 호환: role='tool' 메시지.
        """
