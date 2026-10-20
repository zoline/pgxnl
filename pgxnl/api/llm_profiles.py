"""단계별(ReAct/SQL생성/요약/질문보강) LLM 프로필 저장소.

파이프라인의 코드 구간과 LLM 구간이 분리되어 있어(orchestrator.py), 각 LLM 호출
지점마다 다른 provider/model을 지정할 수 있게 한다. profile_id가 없는(NULL) 단계는
"LLM 설정" 탭의 기본 LLM(state.llm)을 그대로 쓴다 — 기존 단일 프로바이더 설정은
아무것도 바꾸지 않아도 동작한다.

API 키는 pgxnl_user_credentials와 동일하게 Fernet 암호화로 저장하고, 조회 응답에는
원문 대신 has_api_key 같은 상태 플래그만 내려준다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from pgxnl.auth.security import decrypt_api_key, encrypt_api_key

STAGES = (
    "react", "generate_sql", "summarize", "enrich_detect", "enrich_rewrite", "sql_tuning",
    "column_rationale", "canonical_rewrite", "describe_sql",
)
STAGE_LABELS = {
    "react": "ReAct 도구 호출 (스키마 탐색·SQL 생성 추론)",
    "generate_sql": "SQL 생성 폴백 (도구가 SQL을 안 줬을 때)",
    "summarize": "답변 요약 (실행 결과 -> 자연어)",
    "enrich_detect": "질문 보강 - 모호성 판단",
    "enrich_rewrite": "질문 보강 - 재작성",
    "sql_tuning": "SQL 튜닝 (실행계획 분석·재작성·인덱스 제안)",
    "column_rationale": "컬럼 근거 설명 (디버그 전용 — SELECT 항목 ↔ 질문 구절 대조)",
    "canonical_rewrite": "SQL 재작성 (생성 후 — 예시 쌍으로 형태만 교정, 파서 정규화 앞)",
    "describe_sql": "SQL -> 자연어 질문 (수집된 SQL을 캐시에 넣기 전 질문 만들기)",
}


@dataclass
class LlmProfile:
    id: int
    name: str
    provider: str
    model: str
    base_url: str | None
    temperature: float
    max_tokens: int
    has_api_key: bool
    watsonx_project_id: str | None
    watsonx_space_id: str | None
    watsonx_username: str | None
    has_watsonx_password: bool
    watsonx_instance_id: str | None
    watsonx_api_version: str | None
    watsonx_verify_ssl: bool
    is_default: bool
    created_at: datetime


class LlmProfileStore:
    def __init__(self, pool: asyncpg.Pool, secret_key: str) -> None:
        self._pool = pool
        self._secret_key = secret_key

    async def list_profiles(self) -> list[LlmProfile]:
        rows = await self._pool.fetch("SELECT * FROM pgxnl_llm_profiles ORDER BY name")
        return [_to_profile(r) for r in rows]

    async def get_profile(self, profile_id: int) -> LlmProfile | None:
        row = await self._pool.fetchrow("SELECT * FROM pgxnl_llm_profiles WHERE id = $1", profile_id)
        return _to_profile(row) if row else None

    async def get_profile_secrets(self, profile_id: int) -> dict | None:
        """LLM 클라이언트 생성용 — 복호화된 키를 포함한 raw row. 관리 API 응답에는 쓰지 않는다."""
        row = await self._pool.fetchrow("SELECT * FROM pgxnl_llm_profiles WHERE id = $1", profile_id)
        if row is None:
            return None
        d = dict(row)
        d["api_key"] = decrypt_api_key(d["api_key_enc"], self._secret_key) if d.get("api_key_enc") else ""
        d["watsonx_password"] = (
            decrypt_api_key(d["watsonx_password_enc"], self._secret_key) if d.get("watsonx_password_enc") else None
        )
        return d

    async def create_profile(
        self, provider: str, model: str, *, name: str | None = None,
        base_url: str | None = None, temperature: float = 0.0, max_tokens: int = 4096,
        api_key: str | None = None,
        watsonx_project_id: str | None = None, watsonx_space_id: str | None = None,
        watsonx_username: str | None = None, watsonx_password: str | None = None,
        watsonx_instance_id: str | None = None, watsonx_api_version: str | None = None,
        watsonx_verify_ssl: bool = True,
    ) -> LlmProfile:
        name = name or f"{provider}/{model}"
        row = await self._pool.fetchrow(
            """
            INSERT INTO pgxnl_llm_profiles
                (name, provider, model, base_url, temperature, max_tokens, api_key_enc,
                 watsonx_project_id, watsonx_space_id, watsonx_username, watsonx_password_enc,
                 watsonx_instance_id, watsonx_api_version, watsonx_verify_ssl)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
            RETURNING *
            """,
            name, provider, model, base_url, temperature, max_tokens,
            encrypt_api_key(api_key, self._secret_key) if api_key else None,
            watsonx_project_id, watsonx_space_id, watsonx_username,
            encrypt_api_key(watsonx_password, self._secret_key) if watsonx_password else None,
            watsonx_instance_id, watsonx_api_version, watsonx_verify_ssl,
        )
        return _to_profile(row)

    async def update_profile(
        self, profile_id: int, *,
        name: str | None = None, provider: str | None = None, model: str | None = None,
        base_url: str | None = None, temperature: float | None = None, max_tokens: int | None = None,
        api_key: str | None = None,
        watsonx_project_id: str | None = None, watsonx_space_id: str | None = None,
        watsonx_username: str | None = None, watsonx_password: str | None = None,
        watsonx_instance_id: str | None = None, watsonx_api_version: str | None = None,
        watsonx_verify_ssl: bool | None = None,
    ) -> LlmProfile | None:
        current = await self._pool.fetchrow("SELECT * FROM pgxnl_llm_profiles WHERE id = $1", profile_id)
        if current is None:
            return None
        row = await self._pool.fetchrow(
            """
            UPDATE pgxnl_llm_profiles SET
                name = $2, provider = $3, model = $4, base_url = $5, temperature = $6, max_tokens = $7,
                api_key_enc = $8,
                watsonx_project_id = $9, watsonx_space_id = $10, watsonx_username = $11,
                watsonx_password_enc = $12, watsonx_instance_id = $13, watsonx_api_version = $14,
                watsonx_verify_ssl = $15
            WHERE id = $1
            RETURNING *
            """,
            profile_id,
            name if name is not None else current["name"],
            provider if provider is not None else current["provider"],
            model if model is not None else current["model"],
            base_url if base_url is not None else current["base_url"],
            temperature if temperature is not None else current["temperature"],
            max_tokens if max_tokens is not None else current["max_tokens"],
            encrypt_api_key(api_key, self._secret_key) if api_key else current["api_key_enc"],
            watsonx_project_id if watsonx_project_id is not None else current["watsonx_project_id"],
            watsonx_space_id if watsonx_space_id is not None else current["watsonx_space_id"],
            watsonx_username if watsonx_username is not None else current["watsonx_username"],
            encrypt_api_key(watsonx_password, self._secret_key) if watsonx_password else current["watsonx_password_enc"],
            watsonx_instance_id if watsonx_instance_id is not None else current["watsonx_instance_id"],
            watsonx_api_version if watsonx_api_version is not None else current["watsonx_api_version"],
            watsonx_verify_ssl if watsonx_verify_ssl is not None else current["watsonx_verify_ssl"],
        )
        return _to_profile(row)

    async def delete_profile(self, profile_id: int) -> bool:
        row = await self._pool.fetchrow("DELETE FROM pgxnl_llm_profiles WHERE id = $1 RETURNING id", profile_id)
        return row is not None

    async def get_default_profile(self) -> LlmProfile | None:
        row = await self._pool.fetchrow("SELECT * FROM pgxnl_llm_profiles WHERE is_default = true")
        return _to_profile(row) if row else None

    async def set_default_profile(self, profile_id: int) -> None:
        """등록된 모델 중 하나를 "기본 모델"로 지정한다 — 단계가 지정 안 됐을 때 쓰이는
        최종 폴백. 한 번에 하나만 기본일 수 있어 기존 기본을 먼저 해제한다."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("UPDATE pgxnl_llm_profiles SET is_default = false WHERE is_default = true")
            result = await conn.execute(
                "UPDATE pgxnl_llm_profiles SET is_default = true WHERE id = $1", profile_id
            )
            if result == "UPDATE 0":
                raise ValueError("모델을 찾을 수 없습니다")

    # ── 단계 -> 프로필 매핑 ──────────────────────────────────────────

    async def get_stage_config(self) -> dict[str, dict]:
        """반환값: {stage: {"profile_id": int|None, "disable_thinking": bool}}. disable_thinking은
        모델(프로필) 속성이 아니라 "이 단계에서 그 모델을 어떻게 쓸지"라 여기 붙는다 — 같은
        Qwen3 모델을 react(사고 필요)/enrich_detect(속도 중요)에서 다르게 쓸 수 있어야
        모델을 중복 등록할 필요가 없다(사용자 지적으로 프로필 속성에서 옮김)."""
        rows = await self._pool.fetch("SELECT stage, profile_id, disable_thinking FROM pgxnl_llm_stage_config")
        config: dict[str, dict] = {s: {"profile_id": None, "disable_thinking": False} for s in STAGES}
        for r in rows:
            if r["stage"] in config:
                config[r["stage"]] = {"profile_id": r["profile_id"], "disable_thinking": r["disable_thinking"]}
        return config

    async def set_stage_profile(self, stage: str, profile_id: int | None, disable_thinking: bool = False) -> None:
        if stage not in STAGES:
            raise ValueError(f"알 수 없는 단계: {stage}")
        await self._pool.execute(
            """
            INSERT INTO pgxnl_llm_stage_config (stage, profile_id, disable_thinking) VALUES ($1, $2, $3)
            ON CONFLICT (stage) DO UPDATE SET profile_id = EXCLUDED.profile_id, disable_thinking = EXCLUDED.disable_thinking
            """,
            stage, profile_id, disable_thinking,
        )

    # ── 사용자별 개인 설정 ("내 설정" 탭) — 없으면 관리자 기본값을 쓴다 ──────

    async def get_user_stage_config(self, user_id: int) -> dict[str, int | None]:
        rows = await self._pool.fetch(
            "SELECT stage, profile_id FROM pgxnl_user_llm_stage_config WHERE user_id = $1", user_id
        )
        config: dict[str, int | None] = dict.fromkeys(STAGES)
        for r in rows:
            if r["stage"] in config:
                config[r["stage"]] = r["profile_id"]
        return config

    async def set_user_stage_profile(self, user_id: int, stage: str, profile_id: int | None) -> None:
        """profile_id=None은 "관리자 기본값 사용"으로 되돌린다는 뜻 — 개인 설정 행을 지운다."""
        if stage not in STAGES:
            raise ValueError(f"알 수 없는 단계: {stage}")
        if profile_id is None:
            await self._pool.execute(
                "DELETE FROM pgxnl_user_llm_stage_config WHERE user_id = $1 AND stage = $2", user_id, stage
            )
        else:
            await self._pool.execute(
                """
                INSERT INTO pgxnl_user_llm_stage_config (user_id, stage, profile_id) VALUES ($1, $2, $3)
                ON CONFLICT (user_id, stage) DO UPDATE SET profile_id = EXCLUDED.profile_id
                """,
                user_id, stage, profile_id,
            )


def _to_profile(row: asyncpg.Record) -> LlmProfile:
    d = dict(row)
    return LlmProfile(
        id=d["id"], name=d["name"], provider=d["provider"], model=d["model"], base_url=d["base_url"],
        temperature=d["temperature"], max_tokens=d["max_tokens"], has_api_key=bool(d["api_key_enc"]),
        watsonx_project_id=d["watsonx_project_id"], watsonx_space_id=d["watsonx_space_id"],
        watsonx_username=d["watsonx_username"], has_watsonx_password=bool(d["watsonx_password_enc"]),
        watsonx_instance_id=d["watsonx_instance_id"], watsonx_api_version=d["watsonx_api_version"],
        watsonx_verify_ssl=d["watsonx_verify_ssl"], is_default=d["is_default"], created_at=d["created_at"],
    )
