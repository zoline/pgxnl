"""애플리케이션 전역 상태. design 문서 §3(시스템 아키텍처) 참고.

FastAPI lifespan(main.py)에서 초기화되고, 라우터/의존성에서 지연 import로 참조한다
(auth/dependencies.py도 이와 동일한 패턴 사용 — 순환참조 방지).
"""
from __future__ import annotations

import asyncio
import os

import asyncpg

from pgxnl.agent.discovery.statements import SqlStatementStore
from pgxnl.agent.enrichment import QuestionEnricher
from pgxnl.agent.evaluation.store import EvalStore
from pgxnl.agent.orchestrator import Orchestrator
from pgxnl.agent.stats.postgresql import PgStatsAdapter
from pgxnl.api.llm_profiles import LlmProfileStore
from pgxnl.api.targets import TargetStore
from pgxnl.auth.store import UserStore
from pgxnl.cache.schema import SchemaCache
from pgxnl.cache.schema_vector import SchemaVectorIndex
from pgxnl.cache.semantic import SemanticCache
from pgxnl.connectors.postgresql import PgConnector, substitute_dsn_credentials
from pgxnl.governance.glossary import GlossaryStore
from pgxnl.governance.rules import SqlRuleStore
from pgxnl.governance.verified_queries import VerifiedQueryStore
from pgxnl.llm.base import BaseLLMClient
from pgxnl.llm.embeddings import EmbedFn
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser
from pgxnl.settings import Settings, settings


def create_llm_client(s: Settings) -> BaseLLMClient:
    if s.llm_provider == "anthropic":
        from pgxnl.llm.anthropic_client import AnthropicClient

        return AnthropicClient(
            s.llm_model, os.environ.get("ANTHROPIC_API_KEY", ""),
            temperature=s.llm_temperature, max_tokens=s.llm_max_tokens,
        )
    if s.llm_provider == "watsonx":
        from pgxnl.llm.watsonx_client import WatsonxClient

        return WatsonxClient(
            s.llm_model, os.environ.get("WATSONX_API_KEY", ""),
            s.watsonx_project_id, s.llm_base_url or "https://us-south.ml.cloud.ibm.com",
            space_id=s.watsonx_space_id,
            username=s.watsonx_username, password=os.environ.get("WATSONX_PASSWORD") or None,
            instance_id=s.watsonx_instance_id,
            temperature=s.llm_temperature, max_tokens=s.llm_max_tokens,
            api_version=s.watsonx_api_version, verify_ssl=s.watsonx_verify_ssl,
        )
    from pgxnl.llm.openai_compatible import OpenAICompatibleClient

    return OpenAICompatibleClient(
        s.llm_model, s.llm_base_url, os.environ.get("OPENAI_API_KEY", ""),
        temperature=s.llm_temperature, max_tokens=s.llm_max_tokens,
    )


def create_llm_client_from_profile(p: dict, *, disable_thinking: bool = False) -> BaseLLMClient:
    """LlmProfileStore.get_profile_secrets()가 반환한 복호화된 dict로부터 LLM 클라이언트를
    만든다 — create_llm_client(Settings)와 같은 분기 로직을 프로필 레코드 기준으로 반복한다.
    disable_thinking: 프로필 자체의 속성이 아니라 호출자(단계 설정)가 넘겨주는 값이다."""
    if p["provider"] == "anthropic":
        from pgxnl.llm.anthropic_client import AnthropicClient

        return AnthropicClient(p["model"], p["api_key"], temperature=p["temperature"], max_tokens=p["max_tokens"])
    if p["provider"] == "watsonx":
        from pgxnl.llm.watsonx_client import WatsonxClient

        return WatsonxClient(
            p["model"], p["api_key"], p["watsonx_project_id"],
            p["base_url"] or "https://us-south.ml.cloud.ibm.com",
            space_id=p["watsonx_space_id"], username=p["watsonx_username"], password=p["watsonx_password"],
            instance_id=p["watsonx_instance_id"], temperature=p["temperature"], max_tokens=p["max_tokens"],
            api_version=p["watsonx_api_version"] or "2024-05-01", verify_ssl=p["watsonx_verify_ssl"],
        )
    from pgxnl.llm.openai_compatible import OpenAICompatibleClient

    # watsonx_verify_ssl 필드를 그대로 재사용한다 — 이름은 watsonx 전용처럼 보이지만
    # 실제로는 "이 프로필의 base_url에 자체 서명 인증서를 쓰는지" 여부라 provider와
    # 무관하게 의미가 통한다. 별도 컬럼/마이그레이션 없이 이미 DB/등록 화면에 있는
    # 필드를 그대로 쓰는 쪽을 택했다.
    return OpenAICompatibleClient(
        p["model"], p["base_url"], p["api_key"], temperature=p["temperature"], max_tokens=p["max_tokens"],
        verify_ssl=p["watsonx_verify_ssl"], disable_thinking=disable_thinking,
    )


class AppState:
    system_pool: asyncpg.Pool | None = None
    user_store: UserStore | None = None
    target_store: TargetStore | None = None
    schema_cache: SchemaCache | None = None
    semantic_cache: SemanticCache | None = None
    glossary_store: GlossaryStore | None = None
    rule_store: SqlRuleStore | None = None
    statement_store: SqlStatementStore | None = None
    verified_store: VerifiedQueryStore | None = None
    eval_store: EvalStore | None = None
    llm_profile_store: LlmProfileStore | None = None
    llm: BaseLLMClient | None = None
    # main.py에서 state.llm을 재사용해 한 번만 만든다 — 대상 DB(orchestrator)별로
    # create_embed_fn을 따로 호출하면 watsonx 등 세션 기반 provider에서 불필요한
    # 중복 로그인 세션이 생길 수 있어 여기서 공유한다.
    embed_fn: EmbedFn | None = None
    parser: AntlrPostgresParser | None = None
    orchestrators: dict[str, Orchestrator]
    # (user_id, target_name) -> 사용자 전용 자격증명으로 만든 Orchestrator
    user_orchestrators: dict[tuple[int, str], Orchestrator]
    # BIRD 평가 진행 상황 SSE 큐 / 취소 가능한 백그라운드 태스크
    eval_queues: dict[int, asyncio.Queue]
    eval_tasks: dict[int, asyncio.Task]
    # (profile_id, disable_thinking) -> 생성된 LLM 클라이언트 — 같은 프로필이라도 단계마다
    # disable_thinking이 다를 수 있어 튜플로 키를 잡는다. 모델 등록/단계 지정이 바뀌면
    # invalidate_llm_stage_config()로 비운다.
    _model_llm_cache: dict[tuple[int, bool], BaseLLMClient]

    def __init__(self) -> None:
        self.orchestrators = {}
        self.user_orchestrators = {}
        self.eval_queues = {}
        self.eval_tasks = {}
        self._model_llm_cache = {}

    async def get_stage_llm_overrides(self, user_id: int | None = None) -> dict[str, BaseLLMClient]:
        """단계('react'|'generate_sql'|'summarize'|'enrich_detect'|'enrich_rewrite') -> 등록된 모델로 만든 LLM
        클라이언트. 3단계 우선순위로 해석한다: 사용자 개인 설정("내 설정") > 관리자 단계별
        지정 > 등록된 모델 중 기본(is_default). 셋 다 없으면 그 단계는 dict에서 빠지고
        Orchestrator._llm_for()가 .env 기반 self.llm로 최종 폴백한다."""
        if self.llm_profile_store is None:
            return {}
        admin_config = await self.llm_profile_store.get_stage_config()
        default_profile = await self.llm_profile_store.get_default_profile()

        # disable_thinking은 admin_config(단계 설정)에서만 온다 — 사용자 개인 설정은
        # profile_id만 바꿀 수 있고, 그 경우 disable_thinking은 admin 기본 단계 설정값을
        # 그대로 따른다(개인 설정까지 이 값을 따로 갖게 하면 "내 설정" 화면이 복잡해져서
        # 일단 admin 단계 설정에만 둠).
        stage_config: dict[str, dict] = {
            stage: {
                "profile_id": entry["profile_id"] or (default_profile.id if default_profile else None),
                "disable_thinking": entry["disable_thinking"],
            }
            for stage, entry in admin_config.items()
        }
        if user_id is not None:
            user_config = await self.llm_profile_store.get_user_stage_config(user_id)
            for stage, profile_id in user_config.items():
                if profile_id is not None:
                    stage_config[stage]["profile_id"] = profile_id

        overrides: dict[str, BaseLLMClient] = {}
        for stage, entry in stage_config.items():
            profile_id = entry["profile_id"]
            if profile_id is None:
                continue
            cache_key = (profile_id, entry["disable_thinking"])
            if cache_key not in self._model_llm_cache:
                secrets = await self.llm_profile_store.get_profile_secrets(profile_id)
                if secrets is None:
                    continue
                self._model_llm_cache[cache_key] = create_llm_client_from_profile(
                    secrets, disable_thinking=entry["disable_thinking"]
                )
            overrides[stage] = self._model_llm_cache[cache_key]
        return overrides

    def invalidate_llm_stage_config(self) -> None:
        """모델 등록/관리자 기본 단계 지정이 바뀐 뒤 호출 — 캐시된 클라이언트와, 그걸 이미
        물고 있는 Orchestrator들을 전부 비운다(어느 대상이 영향받을지 알 수 없어 전체 무효화)."""
        self._model_llm_cache.clear()
        self.orchestrators.clear()
        self.user_orchestrators.clear()

    async def _build_orchestrator(self, target_name: str, dsn: str, *, user_id: int | None = None) -> Orchestrator:
        target_conn = PgConnector(dsn)
        schema_vector = None
        if self.system_pool is not None:
            schema_vector = SchemaVectorIndex(self.system_pool, self.embed_fn, target_name)

        overrides = await self.get_stage_llm_overrides(user_id=user_id)
        enrich_detect_llm = overrides.get("enrich_detect", self.llm)
        enrich_rewrite_llm = overrides.get("enrich_rewrite", self.llm)

        return Orchestrator(
            target_conn, settings, self.llm, self.parser, target_name,
            system_pool=self.system_pool,
            schema_cache=self.schema_cache,
            schema_vector=schema_vector,
            glossary_store=self.glossary_store,
            rule_store=self.rule_store,
            stats_adapter=PgStatsAdapter(target_conn),
            semantic_cache=self.semantic_cache,
            enrichment=QuestionEnricher(
                enrich_detect_llm, enrich_rewrite_llm, enabled=settings.enrichment_enabled,
                semantic_check_enabled=settings.enrichment_semantic_check_enabled,
            ),
            llm_overrides=overrides,
        )

    async def get_orchestrator(self, target_name: str) -> Orchestrator:
        if target_name in self.orchestrators:
            return self.orchestrators[target_name]
        if self.target_store is None:
            raise RuntimeError("시스템 DB 미연결 — 대상 DB를 조회할 수 없습니다")
        record = await self.target_store.get(target_name)
        if record is None:
            raise TargetNotFoundError(target_name)

        orchestrator = await self._build_orchestrator(target_name, record.dsn)
        self.orchestrators[target_name] = orchestrator
        return orchestrator

    async def get_orchestrator_for_user(self, target_name: str, user_id: int) -> Orchestrator:
        """사용자 전용 DB 자격증명(pgxnl_user_credentials) 또는 단계별 모델 개인 설정
        ("내 설정")이 하나라도 있으면 전용 Orchestrator를, 둘 다 없으면 공유 Orchestrator를
        반환한다."""
        db_cred = None
        if self.user_store is not None:
            db_cred = await self.user_store.get_credential(user_id, target_name)

        has_llm_override = False
        if self.llm_profile_store is not None:
            user_stage_config = await self.llm_profile_store.get_user_stage_config(user_id)
            has_llm_override = any(v is not None for v in user_stage_config.values())

        if db_cred is None and not has_llm_override:
            return await self.get_orchestrator(target_name)

        key = (user_id, target_name)
        if key not in self.user_orchestrators:
            if self.target_store is None:
                raise RuntimeError("시스템 DB 미연결 — 대상 DB를 조회할 수 없습니다")
            record = await self.target_store.get(target_name)
            if record is None:
                raise TargetNotFoundError(target_name)
            dsn = record.dsn
            if db_cred is not None:
                db_user, db_pass = db_cred
                dsn = substitute_dsn_credentials(record.dsn, db_user, db_pass)
            self.user_orchestrators[key] = await self._build_orchestrator(target_name, dsn, user_id=user_id)
        return self.user_orchestrators[key]

    def invalidate_orchestrator(self, target_name: str) -> None:
        self.orchestrators.pop(target_name, None)
        for key in [k for k in self.user_orchestrators if k[1] == target_name]:
            self.user_orchestrators.pop(key, None)

    def invalidate_user_orchestrator(self, user_id: int, target_name: str) -> None:
        self.user_orchestrators.pop((user_id, target_name), None)

    def invalidate_user_orchestrators_all(self, user_id: int) -> None:
        """사용자가 개인 DB 자격증명이 아니라 단계별 모델 개인 설정("내 설정")을 바꾼
        경우 — 어느 대상에 대해 캐시된 Orchestrator든 전부(모든 target_name) 지운다."""
        for key in [k for k in self.user_orchestrators if k[0] == user_id]:
            self.user_orchestrators.pop(key, None)


class TargetNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"대상 DB를 찾을 수 없습니다: {name}")
        self.name = name


state = AppState()
