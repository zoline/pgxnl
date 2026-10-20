"""임베딩 함수 팩토리.

design 문서 §5.6 참고. Schema RAG(§5.4), 문서 지식 레이어(§5.10), 하이브리드
캐시(§5.12)가 공용으로 사용한다. API 키가 비어있거나 'dummy'면 None을 반환해
관련 기능 전체를 비활성화한다 (§2.1 필수/보조 원칙).
"""
from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import openai

from pgxnl.settings import Settings

if TYPE_CHECKING:
    from pgxnl.llm.base import BaseLLMClient

EmbedFn = Callable[[str], Awaitable[list[float]]]


def create_embed_fn(settings: Settings, llm_client: BaseLLMClient | None = None) -> EmbedFn | None:
    """llm_client: 이미 만들어진 채팅용 LLM 클라이언트(state.llm) — provider가 watsonx로
    같으면 재사용해 별도 로그인 세션을 새로 만들지 않는다(계정당 동시 세션을 제한하는
    CPD 배포가 있어, 독립된 클라이언트로 새로 인증하면 기존 세션과 충돌해 401이 날 수
    있다는 게 실측으로 확인됨)."""
    if not settings.embedding_enabled:
        return None

    if settings.embedding_provider == "watsonx":
        from pgxnl.llm.watsonx_client import WatsonxClient

        client = llm_client if isinstance(llm_client, WatsonxClient) else _create_watsonx_embed_client(settings)

        async def embed_watsonx(text: str) -> list[float]:
            return await client.embed(text, model=settings.embedding_model)

        return embed_watsonx

    client = openai.AsyncOpenAI(base_url=settings.embedding_base_url, api_key=settings.embedding_api_key)
    is_openai_hosted = "api.openai.com" in settings.embedding_base_url

    async def embed(text: str) -> list[float]:
        kwargs: dict = {"model": settings.embedding_model, "input": text}
        if is_openai_hosted:
            # vLLM/로컬 서버는 OpenAI의 matryoshka `dimensions` 파라미터를 지원하지 않는다.
            kwargs["dimensions"] = settings.embedding_dimensions
        resp = await client.embeddings.create(**kwargs)
        return resp.data[0].embedding

    return embed


def _create_watsonx_embed_client(settings: Settings) -> BaseLLMClient:
    """llm_client가 없거나 watsonx가 아닐 때(예: 채팅은 다른 provider, 임베딩만 watsonx)의
    폴백 — 이 경우엔 별도 세션이 새로 생기니 계정당 동시 세션 제한이 있는 CPD라면 채팅
    쪽 세션과 충돌할 수 있다는 점을 감안해야 한다."""
    from pgxnl.llm.watsonx_client import WatsonxClient

    return WatsonxClient(
        settings.embedding_model, os.environ.get("WATSONX_API_KEY", ""),
        settings.watsonx_project_id, settings.llm_base_url or "https://us-south.ml.cloud.ibm.com",
        space_id=settings.watsonx_space_id,
        username=settings.watsonx_username, password=os.environ.get("WATSONX_PASSWORD") or None,
        instance_id=settings.watsonx_instance_id,
        api_version=settings.watsonx_api_version, verify_ssl=settings.watsonx_verify_ssl,
    )
