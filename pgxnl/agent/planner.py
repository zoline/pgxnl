"""ReAct Planner. design 문서 §5.5 참고.

Reason -> Act -> Observe 루프. 도구 스키마는 Anthropic 스타일(input_schema)을
canonical 형식으로 사용하며, OpenAI 호환 클라이언트가 내부에서 변환한다
(pgxnl/llm/openai_compatible.py) — Planner는 이 형식 차이를 알지 못한다.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from pgxnl.llm.base import BaseLLMClient, ToolCall

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class ReactPlanner:
    #: `max_tokens`로 잘린 응답이 이 횟수만큼 연달아 나오면 포기한다. 잘린 응답은 도구
    #: 호출이 없어 진전이 없는데, 그 8천 토큰이 대화에 그대로 쌓여 다음 호출을 더 느리고
    #: 더 잘리게 만든다 — 실측(BIRD 465): in:30,023 / out:8,192 한 번에 452초.
    MAX_TRUNCATED_IN_A_ROW = 2

    def __init__(
        self, llm: BaseLLMClient, tools: list[dict[str, Any]], handlers: dict[str, ToolHandler],
        *, max_iterations: int = 20, max_seconds: float | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._handlers = handlers
        self._max_iterations = max_iterations
        # 반복 횟수만으로는 상한이 되지 않는다 — 한 반복이 452초를 쓰면 20회는 2.5시간이다.
        # 평가에서는 문항 하나가 배치 전체를 볼모로 잡는다(실측: run 249·250이 seq 465에서
        # 각각 20분 넘게 멈춰 30문항을 못 끝냈다).
        self._max_seconds = max_seconds

    async def run(
        self, system_prompt: str, question: str,
        *, on_step: Callable[[str], Awaitable[None]] | None = None, debug: bool = False,
    ) -> str:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        t_start = time.monotonic()
        truncated_in_a_row = 0

        async def dbg(msg: str) -> None:
            if debug and on_step is not None:
                await on_step(f"[디버그] {msg}")

        for iteration in range(self._max_iterations):
            if self._max_seconds is not None and time.monotonic() - t_start > self._max_seconds:
                raise TimeoutError(
                    f"ReAct 루프가 제한 시간({self._max_seconds:.0f}초)을 초과했습니다 "
                    f"(반복 {iteration}회 수행)"
                )
            await dbg(f"반복 {iteration + 1}/{self._max_iterations} — LLM 호출 중...")
            t_llm = time.monotonic()
            response = await self._llm.complete(system_prompt, messages, tools=self._tools)
            usage_str = (
                f", tokens=in:{response.usage['input_tokens']}/out:{response.usage['output_tokens']}"
                if response.usage else ""
            )
            await dbg(
                f"반복 {iteration + 1} LLM 응답 ({time.monotonic() - t_llm:.2f}s) "
                f"stop_reason={response.stop_reason}, tool_calls={[tc.name for tc in response.tool_calls]}{usage_str}"
            )
            messages.append(self._llm.format_assistant_message(response))

            if debug and response.text:
                await on_step(f"[디버그] LLM 응답 텍스트(반복 {iteration + 1}): {response.text}")

            if not response.tool_calls:
                if response.stop_reason == "end_turn":
                    return response.text or ""
                if response.stop_reason == "max_tokens":
                    # 출력 상한에 걸려 잘린 응답이다. 그냥 넘기면 그 8천 토큰이 대화에
                    # 쌓여 다음 호출이 더 느리고 더 잘린다 — 짧게 답하라고 되돌린다.
                    truncated_in_a_row += 1
                    if truncated_in_a_row >= self.MAX_TRUNCATED_IN_A_ROW:
                        raise TimeoutError(
                            f"응답이 출력 상한에 걸려 잘린 것이 {truncated_in_a_row}회 "
                            "연속입니다 — 도구 호출을 얻지 못했습니다"
                        )
                    await dbg(f"응답이 출력 상한에 걸려 잘렸습니다({truncated_in_a_row}회 연속) — 짧게 답하도록 요청")
                    messages.append({
                        "role": "user",
                        "content": (
                            "직전 응답이 출력 길이 제한에 걸려 잘렸습니다. 설명을 쓰지 말고 "
                            "바로 도구를 호출하세요. 생각을 길게 적지 말고 다음 한 걸음만 "
                            "수행하세요."
                        ),
                    })
                continue  # 그 밖의 종료 사유 — 다음 반복에서 이어감
            truncated_in_a_row = 0

            finalize_call = next((tc for tc in response.tool_calls if tc.name == "finalize"), None)
            if finalize_call:
                await dbg(f"finalize 호출됨 (반복 {iteration + 1}에서 종료): {finalize_call.input}")
                return finalize_call.input.get("answer", "")

            if on_step is not None:
                for tc in response.tool_calls:
                    await on_step(f"도구 호출: {tc.name}({tc.input})")
                    if debug and isinstance(tc.input, dict) and tc.input.get("reason"):
                        await dbg(f"[이유] {tc.name}: {tc.input['reason']}")

            results = await self._execute_tools(response.tool_calls)

            if debug and on_step is not None:
                for tc, result in results:
                    await on_step(f"[디버그] {tc.name} 결과: {result}")

            tool_result_message = self._llm.format_tool_results(results)
            if isinstance(tool_result_message, list):
                messages.extend(tool_result_message)
            else:
                messages.append(tool_result_message)

        raise TimeoutError(f"ReAct 루프가 최대 반복 횟수({self._max_iterations})를 초과했습니다")

    async def _execute_tools(self, tool_calls: list[ToolCall]) -> list[tuple[ToolCall, Any]]:
        results = []
        for tc in tool_calls:
            handler = self._handlers.get(tc.name)
            if handler is None:
                results.append((tc, f"알 수 없는 도구: {tc.name}"))
                continue
            try:
                result = await handler(tc.input)
            except Exception as exc:  # noqa: BLE001 — 도구 실패는 LLM에게 관찰 결과로 전달
                result = f"오류: {exc}"
            results.append((tc, result))
        return results
