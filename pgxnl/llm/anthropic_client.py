"""Anthropic Claude 클라이언트. Rate limit 시 tenacity로 최대 3회 재시도."""
from __future__ import annotations

from typing import Any

import anthropic
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pgxnl.llm.base import BaseLLMClient, LLMResponse, ToolCall


class AnthropicClient(BaseLLMClient):
    provider = "anthropic"

    def __init__(self, model: str, api_key: str, temperature: float = 0.0, max_tokens: int = 4096) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    @retry(
        retry=retry_if_exception_type(anthropic.RateLimitError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        resp = await self._client.messages.create(
            model=self._model,
            system=system_prompt,
            messages=messages,
            tools=tools or [],
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )
        text = None
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
        usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
        return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=resp.stop_reason or "end_turn", usage=usage)

    def format_assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        if response.text:
            content.append({"type": "text", "text": response.text})
        for tc in response.tool_calls:
            content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
        return {"role": "assistant", "content": content}

    def format_tool_results(self, results: list[tuple[ToolCall, Any]]) -> dict[str, Any]:
        content = [
            {"type": "tool_result", "tool_use_id": tc.id, "content": str(result)}
            for tc, result in results
        ]
        return {"role": "user", "content": content}
