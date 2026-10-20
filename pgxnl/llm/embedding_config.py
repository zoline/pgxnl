"""임베딩 모델 설정 — 시스템 DB(`pgxnl_embedding_config`, 행 하나)에 둔다.

예전에는 `.env`(PGXNL_EMBEDDING_*, EMBEDDING_API_KEY)에 있었다. 설치하고 첫 로그인한 뒤
관리 화면(모델 설정 → 임베딩)에서 정하도록 옮겼다(2026-10-20). 채팅 LLM 과 달리 단계별
지정이 없고 서버 전체가 하나를 쓴다.

- openai_compatible: base_url·model·API 키(선택 — vLLM 처럼 키를 안 보는 서버는 비워도 된다)
- watsonx: 등록된 watsonx 모델(pgxnl_llm_profiles)의 연결·자격을 빌려 쓰고 모델 id 만 따로 둔다

차원은 768 고정이다(db/schema.sql 의 vector(768) 세 곳). 저장 전에 실제로 한 번 임베딩해 차원을 확인한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import asyncpg
import httpx
import openai

from pgxnl.auth.security import decrypt_api_key, encrypt_api_key
from pgxnl.llm.embeddings import EmbedFn

if TYPE_CHECKING:
    from pgxnl.settings import Settings

logger = logging.getLogger(__name__)

EMBEDDING_DIMENSIONS = 768
PROVIDERS = ("openai_compatible", "watsonx")


@dataclass
class EmbeddingConfig:
    provider: str
    model: str
    base_url: str | None = None
    verify_ssl: bool = True
    profile_id: int | None = None   # watsonx: 연결·자격을 빌려 올 등록 모델
    has_api_key: bool = False
    updated_at: datetime | None = None

    def same_model(self, other: EmbeddingConfig | None) -> bool:
        """벡터를 다시 만들어야 하는지 판단용 — 연결 옵션(키·SSL)이 아니라 모델이 같은지."""
        if other is None:
            return False
        return (self.provider, self.model, (self.base_url or "").rstrip("/"), self.profile_id) == (
            other.provider, other.model, (other.base_url or "").rstrip("/"), other.profile_id)


class EmbeddingConfigStore:
    def __init__(self, pool: asyncpg.Pool, secret_key: str) -> None:
        self._pool = pool
        self._secret_key = secret_key

    async def get(self) -> EmbeddingConfig | None:
        row = await self._pool.fetchrow("SELECT * FROM pgxnl_embedding_config WHERE id = 1")
        if row is None:
            return None
        return EmbeddingConfig(
            provider=row["provider"], model=row["model"], base_url=row["base_url"],
            verify_ssl=row["verify_ssl"], profile_id=row["profile_id"],
            has_api_key=bool(row["api_key_enc"]), updated_at=row["updated_at"],
        )

    async def get_api_key(self) -> str:
        enc = await self._pool.fetchval("SELECT api_key_enc FROM pgxnl_embedding_config WHERE id = 1")
        return decrypt_api_key(enc, self._secret_key) if enc else ""

    async def save(self, cfg: EmbeddingConfig, api_key: str | None) -> None:
        """api_key: None 이면 저장된 키를 그대로 둔다(화면은 키를 다시 보여주지 않는다)."""
        enc = encrypt_api_key(api_key, self._secret_key) if api_key else None
        await self._pool.execute(
            """
            INSERT INTO pgxnl_embedding_config (id, provider, model, base_url, verify_ssl, profile_id, api_key_enc, updated_at)
            VALUES (1, $1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (id) DO UPDATE SET
                provider = EXCLUDED.provider, model = EXCLUDED.model, base_url = EXCLUDED.base_url,
                verify_ssl = EXCLUDED.verify_ssl, profile_id = EXCLUDED.profile_id,
                api_key_enc = CASE WHEN $7 THEN EXCLUDED.api_key_enc ELSE pgxnl_embedding_config.api_key_enc END,
                updated_at = now()
            """,
            cfg.provider, cfg.model, cfg.base_url, cfg.verify_ssl, cfg.profile_id, enc, api_key is not None,
        )


def build_openai_embed_fn(cfg: EmbeddingConfig, api_key: str) -> EmbedFn:
    http_client = httpx.AsyncClient(verify=False, timeout=60) if not cfg.verify_ssl else None
    client = openai.AsyncOpenAI(base_url=cfg.base_url, api_key=api_key or "not-needed", http_client=http_client)
    is_openai_hosted = "api.openai.com" in (cfg.base_url or "")

    async def embed(text: str) -> list[float]:
        kwargs: dict = {"model": cfg.model, "input": text}
        if is_openai_hosted:
            # OpenAI 는 matryoshka 절단으로 768 을 낼 수 있다. vLLM 등은 이 파라미터를 지원하지 않는다.
            kwargs["dimensions"] = EMBEDDING_DIMENSIONS
        resp = await client.embeddings.create(**kwargs)
        return resp.data[0].embedding

    return embed


def build_watsonx_embed_fn(cfg: EmbeddingConfig, client) -> EmbedFn:
    async def embed(text: str) -> list[float]:
        return await client.embed(text, model=cfg.model)

    return embed


def legacy_env_config(s: Settings) -> tuple[EmbeddingConfig, str] | None:
    """예전 `.env` 의 임베딩 설정을 시스템 DB 로 한 번 옮길 때 쓴다(DB 에 설정이 없을 때만).

    watsonx 임베딩은 `.env` 의 watsonx 자격을 쓰던 방식이라 등록 모델과 연결할 수 없어 옮기지 않는다.
    """
    key = s.embedding_api_key
    if s.embedding_provider == "watsonx" or not key or key == "dummy":
        return None
    return EmbeddingConfig(provider="openai_compatible", model=s.embedding_model, base_url=s.embedding_base_url), key
