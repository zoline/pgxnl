"""환경변수 기반 전체 설정.

design 문서 §8(환경변수 설정)과 1:1로 대응한다. 모든 보조 기능 플래그의 기본값은
False로 두어, 명시적으로 켜지 않는 한 기존 필수 경로만 동작하도록 한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# pydantic-settings는 .env를 읽어 PGXNL_ 접두사 필드만 채운다. ANTHROPIC_API_KEY,
# OPENAI_API_KEY, WATSONX_API_KEY/WATSONX_PASSWORD처럼 접두사 없이 os.environ에서
# 직접 조회하는 값들은 별도로 로드해야 재기동 후에도 .env에 저장한 값이 실제로
# 반영된다. 이미 존재하는 실제 프로세스 환경변수는 덮어쓰지 않는다(override=False).
load_dotenv(_ENV_PATH, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PGXNL_", env_file=".env", extra="ignore")

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    llm_base_url: str | None = None
    llm_temperature: float = 0.0
    llm_max_tokens: int = 16384

    # LLM: watsonx.ai 전용 (llm_provider="watsonx"일 때만 사용).
    # llm_base_url을 watsonx 엔드포인트로 재사용한다(예: https://us-south.ml.cloud.ibm.com,
    # 또는 Cloud Pak for Data 설치본 URL). watsonx_username이 설정되어 있으면 CPD
    # 자체 인증(/icp4d-api/v1/authorize)을 쓰고, 없으면 IBM Cloud 공개 IAM을 쓴다.
    watsonx_project_id: str | None = None
    watsonx_space_id: str | None = None
    watsonx_username: str | None = None
    watsonx_api_version: str = "2024-05-01"
    # CPD가 내부망 자체서명 인증서를 쓰는 경우가 흔해 끌 수 있게 한다. 기본은 항상 검증.
    watsonx_verify_ssl: bool = True
    # CPD의 Watson Machine Learning REST API에 필요 — 보통 "openshift". IBM Cloud
    # SaaS에서는 불필요(비워둔다).
    watsonx_instance_id: str | None = None

    # Schema RAG / Embedding
    # 임베딩 모델은 2026-10-20 부터 시스템 DB(pgxnl_embedding_config)에서 관리 화면으로 정한다.
    # 아래 embedding_* 와 EMBEDDING_API_KEY 는 **레거시** — 기동 때 DB 에 설정이 없으면 한 번 옮기는
    # 데에만 읽는다(main._migrate_legacy_embedding). 새 설치에서는 .env 에 두지 않는다.
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 768
    embedding_provider: str = "openai_compatible"
    schema_vector_enabled: bool = True
    schema_vector_top_k: int = 10
    # top_k는 상한일 뿐, 점수 하위권 후보를 관련성과 무관하게 그대로 채워 넣는 문제가
    # 있었다 — 1위 후보 점수 대비 이 마진 이내인 것만 남긴다(§5.4 참고). 이 값은
    # 임베딩 모델의 점수 스케일에 종속적이다 — 실측 기준 nomic-embed-text는 점수가
    # 좁게(0.48~0.58대) 뭉쳐 0.05가 적당했지만, granite-embedding-278m-multilingual로
    # 바꾸니 점수 스프레드가 넓어져(0.43~0.69대) 0.15가 맞았다. 너무 타이트하면 정답
    # 테이블이 잘릴 수 있어, 임베딩 모델을 바꾸면 이 값도 함께 재검증해야 한다(§5.4
    # 참고). 코드 기본값은 처음 붙이는 배포를 위해 보수적으로 0.05로 두고, 실제
    # 배포값은 .env에서 쓰는 임베딩 모델에 맞춰 오버라이드한다.
    schema_vector_score_margin: float = 0.05
    # 스키마의 테이블이 이 개수 이하면 마진을 적용하지 않고 전부 스키마 컨텍스트에 넣는다(2026-10-15).
    schema_vector_keep_all_max_tables: int = 3
    # LLM 테이블 선택 단계(2026-10-15) — 임베딩 후보에서 필요한 테이블만 고른다. 켜면 임베딩은 이 마진으로
    # 넓게(재현율 위주) 뽑는다. keep_all_max_tables 이하인 스키마는 선택 단계를 건너뛴다.
    table_select_enabled: bool = False
    table_select_candidate_margin: float = 0.15

    # 질문 보강 (§5.2) — 기본 비활성
    enrichment_enabled: bool = False
    # 패턴 기반으로 못 잡는 의미적 모호성을 LLM으로 2차 판단 — 질문마다 감지용 LLM 호출이
    # 하나 더 늘어나므로(지연시간/비용) 기본은 비활성. enrichment_enabled=true여도 이건
    # 별도로 켜야 한다.
    enrichment_semantic_check_enabled: bool = False

    # SQL Canonicalization / 검증 (§5.8~5.9)
    canonicalization_enabled: bool = True
    validation_max_cost: float = 100_000.0
    audit_log_enabled: bool = True

    # 실행이력 기반 FK 발견 (§5.3) — 기본 비활성
    join_discovery_enabled: bool = False
    join_discovery_schedule: str = "0 3 * * *"

    # Agent
    agent_max_iterations: int = 20
    #: ReAct 루프의 벽시계 상한(초). 반복 횟수만으로는 상한이 되지 않는다 — 한 반복이
    #: 출력 상한(8192토큰)을 다 쓰면 450초가 걸려, 20회면 2.5시간이다. 평가에서는 문항
    #: 하나가 배치 전체를 멈춰 세운다(실측 2026-09-08: seq 465가 20분 넘게 잡고 있어
    #: run 249·250이 27/30에서 끝나지 못했다). 0 이하면 제한 없음.
    agent_max_seconds: float = 300.0
    agent_max_corrections: int = 3
    #: 스키마 컨텍스트에 [Direct Joins]를 넣을지 — 같은 부모를 참조하는 테이블끼리의
    #: 직접 조인 경로다(§mschema.sibling_joins). 정보 자체는 FK 그래프에서 결정론적으로
    #: 나오지만, BIRD california_schools 30문항에서는 EX 25 -> 24로 **중립~음수**였고
    #: 형제 직접 조인 사용도 2건에서 늘지 않았다(run 288). 기본값을 끄고 실험용으로만 켠다.
    #: 켜고 끌 때는 **재색인해야** 저장된 mschema가 갱신된다.
    schema_include_sibling_joins: bool = False
    agent_sample_rows: int = 50
    #: sample_data 도구가 돌려주는 행 수. 실행 결과 행 수(agent_sample_rows)와 분리한다 —
    #: 한 설정을 공유하다가 컬럼이 많은 테이블에서 프롬프트가 터졌다. 실측: schools는
    #: 49컬럼이라 50행이면 57,494자(≈14,400토큰), frpm은 51,243자(≈12,800토큰)다.
    #: 그 둘을 부르면 컨텍스트가 30,000토큰을 넘고, 모델이 출력 상한을 소진하며 한 호출에
    #: 450초를 쓴다(BIRD 465). 이 도구의 목적은 "코드값·날짜 형식 파악"이라 몇 행이면
    #: 충분하다 — 값의 분포가 필요하면 collect_stats가 최빈값과 빈도를 준다.
    agent_sample_data_rows: int = 5
    # 테이블 하나에 붙는 용어집이 이 글자 수를 넘을 때만 질문 관련성으로 거른다(§5.11).
    # 항상 거르게 했더니 BIRD california_schools 30문항에서 EX가 19.7 -> 15.0으로
    # 떨어졌다(6회 vs 4회 실측). 용어집을 0자 받는 문항까지 함께 깨진 것으로 보아
    # 내용이 아니라 schema_context 길이 자체가 모델을 붙들고 있었다 — 지금 규모
    # (테이블당 최대 1.5K자)에서는 거를 이유가 없다. 필터는 용어집이 수십 개로
    # 늘어 프롬프트를 압도할 때를 위한 안전장치이므로 기본값을 그 위로 잡는다.
    glossary_filter_threshold_chars: int = 3000
    agent_stats_top_n: int = 20
    agent_max_context_tables: int = 15

    # 캐시 (§5.12)
    schema_cache_ttl: int = 86_400
    cache_enabled: bool = True
    cache_similarity_threshold: float = 0.85
    cache_embedding_enabled: bool = False
    cache_embedding_threshold: float = 0.90
    cache_ttl_seconds: int = 86_400

    # 시스템 DB
    system_pg_dsn: str = "postgresql://pgxnl:pgxnl@localhost:5432/pgxnl"
    pg_pool_size: int = 10
    pg_max_overflow: int = 20

    # API 서버
    api_host: str = "0.0.0.0"
    api_port: int = 8100
    api_workers: int = 4
    log_level: str = "info"
    secret_key: str = Field(default="CHANGE_ME_32_BYTE_KEY")
    admin_initial_password: str = "passw0rd"

    # 레거시(위 embedding_* 참고)
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")


def persist_env_updates(updates: dict[str, Any]) -> None:
    """PUT /api/admin/settings로 바뀐 값을 .env에도 반영해 재기동 후에도 유지되게 한다.

    updates의 키는 Settings 필드명(snake_case)이며, PGXNL_ 접두사를 붙여 저장한다.
    API 키처럼 접두사 없는 원본 이름 그대로 써야 하는 값은 persist_raw_env_updates를 쓴다.
    """
    kv = {f"PGXNL_{key.upper()}": _format_env_value(value) for key, value in updates.items()}
    _write_env_file(kv)


def persist_raw_env_updates(updates: dict[str, str]) -> None:
    """ANTHROPIC_API_KEY 등 PGXNL_ 접두사가 붙지 않는 환경변수를 .env에 그대로 반영한다."""
    _write_env_file(dict(updates))


def _write_env_file(kv: dict[str, str]) -> None:
    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines() if _ENV_PATH.exists() else []

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        env_key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if env_key in kv:
            new_lines.append(f"{env_key}={kv[env_key]}")
            seen.add(env_key)
        else:
            new_lines.append(line)
    for key, value in kv.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _format_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


settings = Settings()
