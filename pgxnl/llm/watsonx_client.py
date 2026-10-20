"""IBM watsonx.ai 클라이언트.

watsonx.ai의 Text Chat API(`/ml/v1/text/chat`)는 메시지·tool_calls 스키마를
OpenAI 호환에 가깝게 설계해 두었지만(pgxnl/llm/openai_compatible.py와 변환
로직이 유사한 이유), 두 가지가 근본적으로 달라 별도 클라이언트로 구현한다.

1. 인증: 고정 API 키를 바로 Bearer로 쓰는 OpenAI/vLLM/Ollama와 달리, 토큰을 먼저
   발급받아야 하고 그 토큰은 만료되므로 재발급이 필요하다. 배포 형태에 따라 토큰
   발급 방식이 둘로 갈린다 (아래 참고).
2. 요청 형식: model 대신 model_id, 그리고 project_id(또는 space_id) 바디 필드가
   필수다. 엔드포인트에도 version 쿼리 파라미터가 붙는다.

배포 형태 두 가지:
- IBM Cloud SaaS: 공개 IAM(iam.cloud.ibm.com)에 API 키로 토큰을 요청한다.
- Cloud Pak for Data(CPD, 사설/온프렘): 각 설치본 자체의 인증 엔드포인트
  (`{url}/icp4d-api/v1/authorize`)에 username + (api_key 또는 password)로 토큰을
  요청한다 — 공개 IAM은 아예 관여하지 않는다. username이 설정되어 있으면 CPD로
  판단한다.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import httpx

from pgxnl.llm.base import BaseLLMClient, LLMResponse, ToolCall

_IAM_TOKEN_URL = "https://iam.cloud.ibm.com/identity/token"
_DEFAULT_API_VERSION = "2024-05-01"
_DEFAULT_CPD_TOKEN_TTL = 3600  # CPD 응답은 IBM Cloud IAM과 달리 만료시간을 안 주는 경우가 많음
# downstream vLLM 프록시가 "could not decode header"라는 500을 간헐적으로 던지는 걸
# 실측으로 여러 번(서로 다른 BIRD 문항에서) 확인했다 — 우리가 보내는 요청 내용과
# 무관하게 재현되고(같은 요청을 재시도하면 성공하는 경우가 많음) 특정 백엔드 노드가
# 일시적으로 불안정한 것으로 보인다. 5xx만 재시도한다 — 4xx(잘못된 요청/인증)는
# 재시도해도 항상 같은 결과이므로 즉시 실패시키는 게 맞다.
_RETRYABLE_STATUS_MIN = 500
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 1.5

# CPD 게이트웨이가 backend 5xx를 4xx로 감싸서 돌려주는 경우가 있다. 실측(2026-09-02,
# BIRD 평가 30문항이 통째로 실패):
#   403 {"code":"user_authorization_failed",
#        "message":"Failed to find the ... member in project_id ... Error 502 - Bad Gateway"}
# 상태코드만 보면 인증 실패라 즉시 포기해야 할 것 같지만, 본문은 502 게이트웨이 장애다.
# 이런 응답은 재시도로 살아난다 — 본문에 게이트웨이/5xx 신호가 있으면 4xx도 재시도한다.
_GATEWAY_IN_BODY = re.compile(
    r"\b(?:50[0234])\b|bad\s*gateway|gateway\s*time|service\s*unavailable", re.IGNORECASE
)


def _is_retryable(status_code: int, body: str) -> bool:
    if status_code >= _RETRYABLE_STATUS_MIN:
        return True
    return status_code >= 400 and bool(_GATEWAY_IN_BODY.search(body or ""))


_FINISH_REASON_MAP = {
    "tool_calls": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
}


def _strip_backticks(text: str) -> str:
    """이 CPD 배포의 downstream vLLM 프록시가 요청 텍스트에 백틱(`)이 있으면 대화의
    두 번째 호출(도구 호출 결과를 포함한 메시지가 실릴 때)에서 "could not decode
    header"라는 500을 결정론적으로 던지는 걸 실측으로 확인했다(BIRD 문항 evidence의
    마크다운 스타일 백틱 강조 — 예: "represented by `Enrollment (K-12)`" — 로 재현,
    백틱만 제거하면 매번 성공). 재시도로는 못 피하는 결정론적 버그라 아예 보내지
    않는다 — SQL 정체성에 영향 없는 순수 텍스트 강조 표기라 제거해도 의미 손실이
    없다."""
    return text.replace("`", "'")


class WatsonxClient(BaseLLMClient):
    provider = "watsonx"

    def __init__(
        self,
        model: str,
        api_key: str,
        project_id: str | None,
        url: str,
        *,
        space_id: str | None = None,
        username: str | None = None,
        password: str | None = None,
        instance_id: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        api_version: str = _DEFAULT_API_VERSION,
        verify_ssl: bool = True,
    ) -> None:
        # 다른 클라이언트(AnthropicClient, OpenAICompatibleClient)와 마찬가지로
        # 생성 시점에는 검증하지 않는다 — 실제 요청 시점에 명확한 오류로 실패한다.
        # 그래야 watsonx로 전환은 했지만 아직 키를 안 넣은 상태에서도 앱 기동 자체는 막지 않는다.
        self._model = model
        self._api_key = api_key
        self._project_id = project_id
        self._space_id = space_id
        self._username = username
        self._password = password
        self._instance_id = instance_id
        self._url = url.rstrip("/")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._api_version = api_version
        # CPD(사설/온프렘) 설치본은 내부망 전용 자체서명 인증서를 쓰는 경우가 흔해
        # verify_ssl=False 옵션을 둔다 — 기본값은 항상 검증(True).
        self._http = httpx.AsyncClient(timeout=60.0, verify=verify_ssl)
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        # BIRD 평가처럼 concurrency>1로 같은 클라이언트 인스턴스를 동시에 쓰면, 토큰이
        # 아직 없거나 만료된 순간 여러 요청이 동시에 이 메서드에 들어와 각자 새 토큰
        # 발급을 시도하는 race condition이 실제로 재현됐다 — CPD 인증 서버가 같은
        # 계정으로 짧은 시간에 여러 동시 로그인을 401(자격증명 확인 불가)로 거부하는
        # 것으로 보인다. lock으로 토큰 발급을 직렬화해 동시 호출자들이 하나의 발급
        # 결과를 공유하게 한다.
        self._token_lock = asyncio.Lock()

    @property
    def _is_cpd(self) -> bool:
        return bool(self._username)

    async def _get_token(self) -> str:
        # 만료 30초 전에 미리 갱신 — 요청 도중 만료되는 경계 상황을 피한다.
        if self._token is not None and time.time() < self._token_expires_at - 30:
            return self._token
        async with self._token_lock:
            # lock 대기 중 다른 호출자가 이미 갱신했을 수 있다 — 다시 확인 후에만 발급.
            if self._token is not None and time.time() < self._token_expires_at - 30:
                return self._token
            return await self._get_cpd_token() if self._is_cpd else await self._get_iam_token()

    async def _post_with_retry(self, url: str, **kwargs: Any) -> httpx.Response:
        """토큰 발급용 POST. 일시적 장애만 재시도한다.

        예전에는 토큰 발급에 재시도가 **아예 없어서** 5xx나 연결 오류에도 즉시 포기했다.
        complete()/embed()에는 재시도가 있는데 그 앞단인 토큰 발급이 무방비였다.

        **401은 재시도하지 않는다.** 자격증명이 실제로 틀린 경우와 인증 서버의 일시
        장애를 구분할 방법이 없고, 틀린 비밀번호를 반복 전송하면 계정이 잠길 수 있다
        (CPD는 LDAP 연동인 경우가 많다). 2026-09-03에 유효한 자격증명이 잠시 401을
        받아 평가 run 3개를 잃었지만, 그 대가로 계정 잠금을 감수할 수는 없다 —
        연속 실패로 인한 낭비는 평가 하네스가 조기 중단으로 막는다.
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self._http.post(url, **kwargs)
            except httpx.HTTPError as exc:  # 연결 실패/타임아웃도 재시도 대상이다
                last_exc = exc
                if attempt == _MAX_RETRIES:
                    raise
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            if resp.status_code < 400 or not _is_retryable(resp.status_code, resp.text):
                return resp
            if attempt == _MAX_RETRIES:
                return resp
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise last_exc if last_exc else RuntimeError("토큰 발급 재시도 실패")

    async def _get_iam_token(self) -> str:
        resp = await self._post_with_retry(
            _IAM_TOKEN_URL,
            data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": self._api_key},
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"watsonx IAM 토큰 발급 오류 {resp.status_code}: {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    async def _get_cpd_token(self) -> str:
        body: dict[str, str] = {"username": self._username or ""}
        if self._api_key:
            body["api_key"] = self._api_key
        elif self._password:
            body["password"] = self._password
        else:
            raise RuntimeError("watsonx CPD 인증에는 API Key 또는 비밀번호가 필요합니다")

        resp = await self._post_with_retry(
            f"{self._url}/icp4d-api/v1/authorize",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            json=body,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"watsonx CPD 토큰 발급 오류 {resp.status_code}: {resp.text}")
        data = resp.json()
        self._token = data["token"]
        self._token_expires_at = time.time() + _DEFAULT_CPD_TOKEN_TTL
        return self._token

    @staticmethod
    def _to_watsonx_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
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
        if not self._api_key and not (self._is_cpd and self._password):
            raise RuntimeError("WATSONX_API_KEY가 설정되어 있지 않습니다")
        if not self._project_id and not self._space_id:
            raise RuntimeError("PGXNL_WATSONX_PROJECT_ID(또는 watsonx_space_id)가 설정되어 있지 않습니다")

        token = await self._get_token()
        sanitized_messages = [
            {**m, "content": _strip_backticks(m["content"])} if isinstance(m.get("content"), str) else m
            for m in messages
        ]
        body: dict[str, Any] = {
            "model_id": self._model,
            "messages": [{"role": "system", "content": _strip_backticks(system_prompt)}, *sanitized_messages],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if self._space_id:
            body["space_id"] = self._space_id
        else:
            body["project_id"] = self._project_id
        if tools:
            body["tools"] = self._to_watsonx_tools(tools)

        params = {"version": self._api_version}
        if self._instance_id:
            # Cloud Pak for Data의 Watson Machine Learning REST API는 IBM Cloud SaaS와
            # 달리 서비스 인스턴스를 CRN이 아니라 instance_id로 구분한다(관례상 "openshift").
            params["instance_id"] = self._instance_id

        resp = None
        for attempt in range(_MAX_RETRIES + 1):
            resp = await self._http.post(
                f"{self._url}/ml/v1/text/chat",
                params=params,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            if not _is_retryable(resp.status_code, resp.text) or attempt == _MAX_RETRIES:
                break
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        assert resp is not None
        if resp.status_code >= 400:
            # httpx의 기본 HTTPStatusError 메시지에는 응답 본문이 없어 실제 원인(예:
            # 잘못된 model_id, 미지원 파라미터)을 알 수 없다 — 본문을 그대로 포함시킨다.
            raise RuntimeError(f"watsonx API 오류 {resp.status_code}: {resp.text}")
        data = resp.json()
        choice = data["choices"][0]
        message = choice["message"]
        text = message.get("content")
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["function"]["name"], input=json.loads(tc["function"]["arguments"]))
            for tc in (message.get("tool_calls") or [])
        ]
        stop_reason = _FINISH_REASON_MAP.get(choice.get("finish_reason"), choice.get("finish_reason") or "end_turn")
        raw_usage = data.get("usage") or {}
        usage = (
            {"input_tokens": raw_usage["prompt_tokens"], "output_tokens": raw_usage["completion_tokens"]}
            if "prompt_tokens" in raw_usage and "completion_tokens" in raw_usage else None
        )
        return LLMResponse(text=text, tool_calls=tool_calls, stop_reason=stop_reason, usage=usage)

    async def embed(self, text: str, *, model: str | None = None) -> list[float]:
        """텍스트 임베딩(`/ml/v1/text/embeddings`). `complete()`과 동일한 `_get_token()`
        캐시를 재사용해 채팅과 별도 세션을 새로 만들지 않는다 — 이 CPD 배포는 계정당
        동시 토큰 세션을 제한하는 것으로 관찰되어, 독립된 클라이언트로 새로 로그인하면
        기존 세션과 충돌해 401이 난다. model을 안 주면 이 클라이언트의 채팅 모델을 쓴다."""
        token = await self._get_token()
        body: dict[str, Any] = {"model_id": model or self._model, "inputs": [text]}
        if self._space_id:
            body["space_id"] = self._space_id
        else:
            body["project_id"] = self._project_id

        params = {"version": self._api_version}
        if self._instance_id:
            params["instance_id"] = self._instance_id

        # complete()과 같은 재시도를 적용한다 — 원래 embed()에는 재시도가 없어서,
        # 게이트웨이가 한 번 흔들리면 평가 배치가 통째로 무너졌다(실측: 30문항 중 15문항).
        resp = None
        for attempt in range(_MAX_RETRIES + 1):
            resp = await self._http.post(
                f"{self._url}/ml/v1/text/embeddings",
                params=params,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            if not _is_retryable(resp.status_code, resp.text) or attempt == _MAX_RETRIES:
                break
            await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
        assert resp is not None
        if resp.status_code >= 400:
            raise RuntimeError(f"watsonx 임베딩 API 오류 {resp.status_code}: {resp.text}")
        data = resp.json()
        return data["results"][0]["embedding"]

    def format_assistant_message(self, response: LLMResponse) -> dict[str, Any]:
        tool_calls = [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.input)}}
            for tc in response.tool_calls
        ] or None
        content = response.text
        if content is None and tool_calls is None:
            # openai_compatible.py의 동일 수정 참고 — reasoning 모델이 max_tokens를 사고
            # 과정만으로 다 써버리면 content/tool_calls가 둘 다 없는 응답이 올 수 있는데,
            # 이걸 그대로 히스토리에 넣으면 다음 턴 요청에서 엄격한 서버가 거부할 수 있다.
            content = ""
        return {"role": "assistant", "content": content, "tool_calls": tool_calls}

    def format_tool_results(self, results: list[tuple[ToolCall, Any]]) -> list[dict[str, Any]]:
        return [{"role": "tool", "tool_call_id": tc.id, "content": str(result)} for tc, result in results]
