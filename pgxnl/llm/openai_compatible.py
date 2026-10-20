"""OpenAI 호환(vLLM, Ollama) 클라이언트.

Anthropic의 input_schema를 OpenAI의 parameters 포맷으로 변환하는 부분을 이 안에서
흡수한다 — ReAct Planner는 두 포맷 차이를 알 필요가 없다 (design 문서 §5.5).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import openai

from pgxnl.llm.base import BaseLLMClient, LLMResponse, ToolCall

_FINISH_REASON_MAP = {
    "tool_calls": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
}


class OpenAICompatibleClient(BaseLLMClient):
    provider = "openai"

    #: LLM 호출 하나의 상한(초). 정상 호출은 3~10초, 스키마 탐색이 붙어도 60초 안쪽이다
    #: (실측). 이 값을 넘긴 호출은 모델이 출력 상한을 소진하며 겉돌고 있는 것이라,
    #: 기다려도 쓸 만한 응답이 나오지 않는다.
    REQUEST_TIMEOUT = 180.0

    #: 순간 장애(연결 끊김·5xx·429)에 대한 재시도 횟수. **시간 초과는 재시도하지 않는다** —
    #: openai SDK 기본(max_retries=2)은 타임아웃도 처음부터 다시 생성해서, 상한을 넘기는
    #: 긴 응답은 180초×3 = 9분 뒤에야 실패했다(2026-10-02 Design Lab LLM 의견 실측,
    #: 사용자 결정으로 끔). 같은 요청을 다시 보내도 같은 길이로 생성하므로 결과는 같다.
    TRANSIENT_RETRIES = 2

    def __init__(
        self, model: str, base_url: str | None, api_key: str, temperature: float = 0.0, max_tokens: int = 4096,
        verify_ssl: bool = True, disable_thinking: bool = False,
    ) -> None:
        # vLLM/Ollama처럼 인증 없는 자체 호스팅 서버를 쓸 때는 등록 화면에서 api_key를
        # 비워두는 게 정상인데, openai SDK는 빈 문자열/None을 "자격증명 누락"으로 보고
        # 클라이언트 생성 시점에 바로 예외를 던진다(실제 HTTP 요청은 가지도 않음) —
        # 그래서 등록 테스트가 접속·모델명과 무관하게 항상 실패했다. 서버가 키를
        # 검사하지 않으면 어떤 non-empty 문자열이든 무해하므로 플레이스홀더로 대체한다.
        #
        # verify_ssl: 자체 서명 인증서를 쓰는 사내 vLLM 서버(HTTPS 전환 시 흔함)를
        # 그대로 붙이면 openai SDK(내부적으로 httpx)가 인증서 검증에서 막혀
        # APIConnectionError를 던지는 걸 실측 확인했다(curl -k로는 되는데 SDK로는
        # 안 되는 상황) — False면 httpx 클라이언트를 직접 만들어 검증을 끈다.
        #
        # 타임아웃: openai SDK 기본값은 600초라 사실상 무한대다. 컨텍스트가 커지면 모델이
        # 출력 상한을 다 쓰며 한 호출에 450초를 쓰는 것을 실측했다(BIRD 465: in:30,023 /
        # out:8,192 / 452초) — 그동안 평가 배치 전체가 멈춰 선다. ReAct 루프의 벽시계
        # 제한(agent_max_seconds)은 반복 **시작** 시점에만 검사하므로 호출 하나가 길어지는
        # 것은 못 막는다. 호출 단위로도 상한이 필요하다.
        http_client = httpx.AsyncClient(verify=False, timeout=OpenAICompatibleClient.REQUEST_TIMEOUT) if not verify_ssl else None
        self._client = openai.AsyncOpenAI(
            base_url=base_url, api_key=api_key or "not-needed", http_client=http_client,
            timeout=OpenAICompatibleClient.REQUEST_TIMEOUT,
            max_retries=0,  # 재시도는 complete()가 직접 고른다(시간 초과 제외)
        )
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        # Qwen3류 하이브리드 reasoning 모델은 간단한 모호성 판단 같은 짧은 요청에도
        # 사고 과정을 먼저 생성한다 — max_tokens를 사고에만 다 쓰고 실제 답변을 못
        # 낼 수도 있고(실측 확인), 속도도 크게 느려진다(8분 넘게 걸리는 것도 실측
        # 확인). vLLM의 chat_template_kwargs.enable_thinking=false로 끄면 같은
        # 요청이 0.35초로 끝나는 것까지 실측 확인했다 — Qwen 계열이 아닌 서버는 이
        # extra_body 필드를 그냥 무시하므로 무해하다.
        self._extra_body = {"chat_template_kwargs": {"enable_thinking": False}} if disable_thinking else None

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],  # Anthropic 스타일 -> OpenAI 'parameters'
                },
            }
            for t in tools
        ]

    async def complete(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        resp = await self._create_with_retry(
            model=self._model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
            tools=self._to_openai_tools(tools) if tools else None,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            extra_body=self._extra_body,
        )
        choice = resp.choices[0]
        tool_calls = [
            ToolCall(id=tc.id, name=tc.function.name, input=json.loads(tc.function.arguments))
            for tc in (choice.message.tool_calls or [])
        ]
        stop_reason = _FINISH_REASON_MAP.get(choice.finish_reason, choice.finish_reason)
        usage = (
            {"input_tokens": resp.usage.prompt_tokens, "output_tokens": resp.usage.completion_tokens}
            if resp.usage else None
        )
        return LLMResponse(text=choice.message.content, tool_calls=tool_calls, stop_reason=stop_reason, usage=usage)

    async def _create_with_retry(self, **kwargs: Any) -> Any:
        for attempt in range(self.TRANSIENT_RETRIES + 1):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except openai.APITimeoutError:
                # APIConnectionError 의 하위 클래스라 먼저 잡아 바로 올린다.
                raise
            except (openai.APIConnectionError, openai.InternalServerError, openai.RateLimitError):
                if attempt == self.TRANSIENT_RETRIES:
                    raise
                await asyncio.sleep(0.5 * 2 ** attempt)
        raise AssertionError("unreachable")

    def format_assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        tool_calls = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
            }
            for tc in response.tool_calls
        ] or None
        content = response.text
        if content is None and tool_calls is None:
            # reasoning 모델이 max_tokens를 사고 과정만으로 다 써버리면 content도
            # tool_calls도 없는 응답이 온다(실측 확인: Qwen3 계열, finish_reason=length).
            # 이걸 그대로 히스토리에 넣으면 assistant 메시지에 content/tool_calls가 둘 다
            # None이 되는데, OpenAI 스펙상 최소 하나는 있어야 해서 vLLM처럼 엄격하게
            # pydantic 검증하는 서버는 다음 턴 요청 자체를 400으로 거부한다(실측 확인,
            # "Bad Request" 재현) — 빈 문자열로 채워 최소 유효성을 보장한다.
            content = ""
        return {"role": "assistant", "content": content, "tool_calls": tool_calls}

    def format_tool_results(self, results: list[tuple[ToolCall, Any]]) -> list[dict[str, Any]]:
        # OpenAI 호환은 tool 결과마다 별도 메시지이므로 리스트를 반환한다.
        # Planner 쪽에서 단일 dict를 기대하면 messages.extend(...)로 풀어서 사용한다.
        return [{"role": "tool", "tool_call_id": tc.id, "content": str(result)} for tc, result in results]
