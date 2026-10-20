-- pgxnl 시스템 PostgreSQL 스키마. design 문서 §7과 1:1 대응.
-- 적용: psql "$PGXNL_SYSTEM_PG_DSN" -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 사용자
CREATE TABLE IF NOT EXISTS pgxnl_users (
    id              SERIAL      PRIMARY KEY,
    username        TEXT        UNIQUE NOT NULL,
    email           TEXT,
    role            TEXT        NOT NULL DEFAULT 'user',
    api_key_hash    TEXT        UNIQUE NOT NULL,
    api_key_prefix  TEXT        NOT NULL,
    api_key_enc     TEXT        NOT NULL,
    password_hash   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 대상 DB 메타스토어
CREATE TABLE IF NOT EXISTS pgxnl_targets (
    id              SERIAL      PRIMARY KEY,
    name            TEXT        UNIQUE NOT NULL,
    dialect         TEXT        NOT NULL DEFAULT 'postgresql',
    dsn_encrypted   TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 스키마 캐시 (DDL / 통계 / 목록)
CREATE TABLE IF NOT EXISTS pgxnl_schema_cache (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT        NOT NULL,
    cache_key   TEXT        NOT NULL,   -- ddl: / tables: / search: / stats:
    data        JSONB       NOT NULL,
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_name, cache_key)
);
CREATE INDEX IF NOT EXISTS idx_pgxnl_schema_cache_lookup
    ON pgxnl_schema_cache (target_name, cache_key);

-- 스키마 벡터 인덱스 (경량 표현 + M-Schema)
-- 768차원 = Ollama nomic-embed-text 기본 출력 차원에 맞춘 것. 다른 임베딩 모델을
-- 쓴다면(OpenAI text-embedding-3-small 등) 그 모델의 실제 출력 차원으로 바꿔야 한다.
CREATE TABLE IF NOT EXISTS pgxnl_schema_vectors (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT        NOT NULL,
    schema_name TEXT        NOT NULL,
    table_name  TEXT        NOT NULL,
    doc         TEXT        NOT NULL,      -- 경량 표현 (임베딩 원문)
    mschema     JSONB       NOT NULL,      -- 값 예시 포함 전체 M-Schema
    embedding   vector(768),
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_name, schema_name, table_name)
);
-- 기존 설치본이 다른 차원(예: 이전 기본값 1024)으로 만들어졌다면 접속 시마다 맞춘다.
-- 데이터가 있는 상태에서 차원을 바꾸면 그 행들의 벡터는 무효가 되니 재색인이 필요하다.
ALTER TABLE pgxnl_schema_vectors ALTER COLUMN embedding TYPE vector(768);
CREATE INDEX IF NOT EXISTS idx_pgxnl_schema_vectors_hnsw
    ON pgxnl_schema_vectors USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 실행이력 기반 FK 후보
CREATE TABLE IF NOT EXISTS pgxnl_join_candidates (
    id            SERIAL PRIMARY KEY,
    target_name   TEXT NOT NULL,
    table_a       TEXT NOT NULL,
    column_a      TEXT NOT NULL,
    table_b       TEXT NOT NULL,
    column_b      TEXT NOT NULL,
    source        TEXT NOT NULL,    -- 'history' | 'pattern' | 'histogram' | 'sample'
    confidence    REAL NOT NULL,
    calls         INTEGER,
    reviewed      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_name, table_a, column_a, table_b, column_b)
);
-- 스키마를 별도 열로(2026-10-07). 전엔 스키마를 테이블 이름 앞에 붙여(`card_games.cards`) 저장했는데,
-- 붙이는 일을 호출자에게 맡겨 경로마다 달랐다 — 실행이력은 붙이고 Design Lab·수동 등록은 안 붙여
-- BIRD 21건 중 6건이 스키마 없이 쌓였다. 규칙·용어집처럼 schema_name 열에 두고 table_a/table_b 는
-- 맨 이름만. '' = 스키마 미상(카탈로그로 못 정한 것 — 그 대상의 모든 스키마에 맨 이름으로 맞춘다).
ALTER TABLE pgxnl_join_candidates ADD COLUMN IF NOT EXISTS schema_name TEXT NOT NULL DEFAULT '';
ALTER TABLE pgxnl_join_candidates DROP CONSTRAINT IF EXISTS pgxnl_join_candidates_target_name_table_a_column_a_table_b__key;
-- 이전: 양쪽이 같은 스키마로 한정된 행만 옮긴다(스키마를 넘나드는 관계는 그대로 둔다 — 2026-10-07 0건).
UPDATE pgxnl_join_candidates
   SET schema_name = split_part(table_a, '.', 1),
       table_a = substr(table_a, length(split_part(table_a, '.', 1)) + 2),
       table_b = substr(table_b, length(split_part(table_b, '.', 1)) + 2)
 WHERE schema_name = '' AND table_a LIKE '%.%' AND table_b LIKE '%.%'
   AND split_part(table_a, '.', 1) = split_part(table_b, '.', 1);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pgxnl_join_candidates_edge
    ON pgxnl_join_candidates (target_name, schema_name, table_a, column_a, table_b, column_b);
-- 방향도 graph.edge_key 와 같은 규칙(맨 이름 기준 (테이블, 컬럼) 오름차순, 바이트 순)으로 맞춘다 —
-- 예전 행은 한정 이름 기준이거나 정렬 전 코드로 들어와 반대 방향인 것이 있었고(dvdrental
-- film_actor→film), 그대로 두면 같은 관계가 다시 들어올 때 중복 행이 생긴다. 반대 방향 행이 이미
-- 있으면(중복) 건드리지 않는다.
UPDATE pgxnl_join_candidates j
   SET table_a = j.table_b, column_a = j.column_b, table_b = j.table_a, column_b = j.column_a
 WHERE (j.table_a COLLATE "C", j.column_a COLLATE "C") > (j.table_b COLLATE "C", j.column_b COLLATE "C")
   AND NOT EXISTS (
       SELECT 1 FROM pgxnl_join_candidates k
        WHERE k.target_name = j.target_name AND k.schema_name = j.schema_name
          AND k.table_a = j.table_b AND k.column_a = j.column_b
          AND k.table_b = j.table_a AND k.column_b = j.column_a);

-- 하이브리드 시맨틱 캐시
CREATE TABLE IF NOT EXISTS pgxnl_cache (
    id          SERIAL      PRIMARY KEY,
    target_db   TEXT        NOT NULL,
    schema_name TEXT        NOT NULL DEFAULT 'public',
    question    TEXT        NOT NULL,
    answer      TEXT        NOT NULL,
    sql_steps   JSONB       NOT NULL DEFAULT '[]',
    embedding   vector(768),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hit_count   INTEGER     NOT NULL DEFAULT 0
);
-- 기존 설치본에는 없을 수 있는 컬럼 — 같은 target_db 안에서도 스키마(BIRD의
-- db_id별 스키마처럼)가 다르면 같은 질문이라도 정답이 달라질 수 있어, target_db
-- 만으로 캐시 키를 잡으면 스키마를 넘나들며 잘못된 캐시가 히트할 수 있다(실측으로
-- 확인). 기본값 'public'은 이전까지 schema 파라미터가 항상 public으로 고정이었던
-- 것과 동일하게 동작하도록 하기 위함.
ALTER TABLE pgxnl_cache ADD COLUMN IF NOT EXISTS schema_name TEXT NOT NULL DEFAULT 'public';
ALTER TABLE pgxnl_cache ALTER COLUMN embedding TYPE vector(768);
CREATE INDEX IF NOT EXISTS idx_pgxnl_cache_trgm ON pgxnl_cache USING GIN (question gin_trgm_ops);
-- CREATE INDEX IF NOT EXISTS는 이름만 보고 스킵하므로, 컬럼 구성이 바뀐 기존
-- 설치본의 인덱스를 갱신하려면 이름으로 지우고 새로 만들어야 한다.
DROP INDEX IF EXISTS idx_pgxnl_cache_target;
CREATE INDEX IF NOT EXISTS idx_pgxnl_cache_target ON pgxnl_cache (target_db, schema_name, created_at DESC);

-- 거버넌스: SQL 생성 규칙
CREATE TABLE IF NOT EXISTS pgxnl_rules (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT,                       -- NULL이면 전역 규칙
    rule_type   TEXT        NOT NULL,        -- 'canonicalization' | 'generation_constraint'
    definition  JSONB       NOT NULL,
    enabled     BOOLEAN     NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 스키마 단위 규칙(2026-10-06). NULL 이면 대상 전체. BIRD 처럼 대상 하나에 스키마가 여럿이면
-- 한 스키마의 컬럼을 언급하는 규칙(canonical_column 매핑, null_ratio 발동 낱말 등)이 다른
-- 스키마 질문에도 걸렸다. 용어집(pgxnl_glossary.schema_name)과 같은 축이다.
ALTER TABLE pgxnl_rules ADD COLUMN IF NOT EXISTS schema_name TEXT;

-- 거버넌스: 업무 용어집
CREATE TABLE IF NOT EXISTS pgxnl_glossary (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT,
    schema_name TEXT,
    term        TEXT        NOT NULL,
    table_name  TEXT,
    column_name TEXT,
    definition  TEXT        NOT NULL,
    is_pii      BOOLEAN     NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- 기존 설치본에는 없을 수 있는 컬럼 — target_name 안에 스키마가 여러 개인 경우(BIRD
-- 등)에 스키마 구분 없이 매칭되면 다른 스키마의 동명 테이블에도 잘못 적용되는 문제가
-- 있었다(시맨틱 캐시에서 겪은 것과 같은 종류). NULL은 target_name과 같은 관례로
-- "스키마 무관하게 적용" — 기존 행은 전부 NULL이 되어 기존 동작을 그대로 유지한다.
ALTER TABLE pgxnl_glossary ADD COLUMN IF NOT EXISTS schema_name TEXT;
-- 외부 공식 문서(예: CDE 공립학교 파일 구조 문서)에서 가져온 정의의 출처를 남긴다 —
-- 원본 문서 전체를 별도 저장소에 들고 있지 않기로 했으므로(구조화된 코드-값 매핑은
-- 검색 대상 문서가 아니라 glossary 항목 자체가 최종 형태), 출처 URL/문서명만
-- 추적 가능하게 남겨 나중에 재검증·갱신할 때 원본을 다시 찾을 수 있게 한다.
ALTER TABLE pgxnl_glossary ADD COLUMN IF NOT EXISTS source TEXT;
-- enrichment(질문 보강, 스키마 링킹 이전 단계)도 glossary를 참고하게 만들면서, 항목마다
-- "어느 단계에서 쓰일지"를 구분할 필요가 생겼다 — DOC/SOC처럼 SQL 생성에만 필요한 큰 값
-- 표까지 매번 enrichment 판단에도 실으면 토큰만 늘고 득이 없다(실측: enrichment는 스키마를
-- 모르는 채로 도는 가벼운 전처리라, "이미 존재하는 컬럼"을 몰라 재작성이 오히려 SQL을
-- 망치는 사례를 여러 번 확인함 — glossary를 참고하게 하되 필요한 항목만 골라 보여줘야
-- 함). on/off(예전 enabled 열) 하나로는 이 구분을 표현 못 해 4값 scope로 대체한다: 'enrich'(질문
-- 보강 전용), 'generation'(SQL 생성 전용), 'both'(둘 다), 'disabled'(비활성). NULL로
-- 남아있는 행(신규 컬럼 추가 직후)만 기존 enabled 값 기준으로 한 번 채워 넣는다 — 이미
-- scope가 채워진 행은 관리자가 명시적으로 바꿨을 수 있으므로 재실행 시 덮어쓰지 않는다.
ALTER TABLE pgxnl_glossary ADD COLUMN IF NOT EXISTS scope TEXT;
-- 예전 on/off 열(enabled)은 2026-10-12 삭제했다. 코드는 scope 만 읽는데 열이 남아 있어, 2026-10-06
-- enabled=false 로 "끈" 항목(#97)이 실제로는 계속 켜져 run 358~366 측정을 오염시켰다. 열이 남아
-- 있는 설치본에서만 한 번 옮기고(scope 가 비었으면 그 값으로, enabled=false 면 disabled 로) 지운다.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'pgxnl_glossary' AND column_name = 'enabled') THEN
        UPDATE pgxnl_glossary SET scope = CASE WHEN enabled THEN 'both' ELSE 'disabled' END WHERE scope IS NULL;
        UPDATE pgxnl_glossary SET scope = 'disabled' WHERE NOT enabled AND scope <> 'disabled';
        ALTER TABLE pgxnl_glossary DROP COLUMN enabled;
    END IF;
END $$;
UPDATE pgxnl_glossary SET scope = 'both' WHERE scope IS NULL;
ALTER TABLE pgxnl_glossary ALTER COLUMN scope SET DEFAULT 'both';
ALTER TABLE pgxnl_glossary ALTER COLUMN scope SET NOT NULL;

-- 감사 로그
CREATE TABLE IF NOT EXISTS pgxnl_audit_log (
    id             SERIAL PRIMARY KEY,
    target_name    TEXT NOT NULL,
    user_id        INTEGER REFERENCES pgxnl_users(id),
    question       TEXT,
    sql            TEXT NOT NULL,
    decision       TEXT NOT NULL,     -- 'allowed' | 'rejected' | 'correction_requested'
    reason         TEXT,
    estimated_cost REAL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pgxnl_audit_log_target_time
    ON pgxnl_audit_log (target_name, created_at DESC);

-- 사용자별 DB 자격증명 (분석 시 대상 DB에 이 자격증명으로 접속)
CREATE TABLE IF NOT EXISTS pgxnl_user_credentials (
    id           SERIAL      PRIMARY KEY,
    user_id      INTEGER     NOT NULL REFERENCES pgxnl_users(id) ON DELETE CASCADE,
    target_name  TEXT        NOT NULL,
    db_username  TEXT        NOT NULL,
    password_enc TEXT        NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, target_name)
);

-- 수집된 SQL statement (pg_stat_statements 또는 파일 업로드)
CREATE TABLE IF NOT EXISTS pgxnl_sql_statements (
    id            BIGSERIAL   PRIMARY KEY,
    target_name   TEXT        NOT NULL,
    sql_hash      TEXT        NOT NULL,
    sql_text      TEXT        NOT NULL,
    sql_type      TEXT        NOT NULL DEFAULT 'other',
    call_count    BIGINT      NOT NULL DEFAULT 1,
    total_time_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    mean_time_ms  DOUBLE PRECISION NOT NULL DEFAULT 0,
    tables_used   JSONB       NOT NULL DEFAULT '[]',
    source        TEXT        NOT NULL DEFAULT 'manual',
    collected_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_name, sql_hash)
);
CREATE INDEX IF NOT EXISTS idx_pgxnl_sql_statements_target
    ON pgxnl_sql_statements (target_name, collected_at DESC);

-- BIRD 벤치마크 평가
CREATE TABLE IF NOT EXISTS pgxnl_eval_runs (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT        NOT NULL,
    run_name    TEXT        NOT NULL DEFAULT '',
    -- 'infra_failed': 외부 의존성 장애(watsonx 토큰/임베딩 API 등)로 중단된 run.
    -- 'done'과 반드시 구분해야 한다 — 그렇지 않으면 0/30 같은 값이 측정값으로 오인된다.
    status      TEXT        NOT NULL DEFAULT 'running',   -- 'running' | 'done' | 'cancelled' | 'infra_failed'
    total       INTEGER     NOT NULL DEFAULT 0,
    done        INTEGER     NOT NULL DEFAULT 0,
    correct_ex  INTEGER     NOT NULL DEFAULT 0,
    correct_em  INTEGER     NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_pgxnl_eval_runs_target
    ON pgxnl_eval_runs (target_name, created_at DESC);

CREATE TABLE IF NOT EXISTS pgxnl_eval_items (
    id           BIGSERIAL   PRIMARY KEY,
    run_id       INTEGER     NOT NULL REFERENCES pgxnl_eval_runs(id) ON DELETE CASCADE,
    seq          INTEGER     NOT NULL DEFAULT 0,
    question_id  TEXT        NOT NULL DEFAULT '',
    db_id        TEXT        NOT NULL DEFAULT '',   -- BIRD 평가 문항별 대상 스키마
    difficulty   TEXT        NOT NULL DEFAULT '',
    question     TEXT        NOT NULL,
    evidence     TEXT        NOT NULL DEFAULT '',
    gold_sql     TEXT        NOT NULL,
    pred_sql     TEXT,
    ex_pass      BOOLEAN,
    em_pass      BOOLEAN,
    error        TEXT,
    elapsed_ms   DOUBLE PRECISION
);
-- 기존 설치본 호환: db_id 컬럼이 없으면 추가 (매 접속 시 실행되어도 안전)
ALTER TABLE pgxnl_eval_items ADD COLUMN IF NOT EXISTS db_id TEXT NOT NULL DEFAULT '';
-- 공식 BIRD 채점(2026-10-06): `set(pred) == set(gold)` — 중복·순서 무시, 정규화 없음
-- (bird-bench/mini_dev evaluation/evaluation_ex.py). ex_pass(pgxnl)는 중복 개수까지 비교해 더 엄격하다.
-- NULL = 아직 계산 안 됨(이 열을 넣기 전의 run). run 쪽 correct_ex_official 도 NULL 이면 미계산.
ALTER TABLE pgxnl_eval_items ADD COLUMN IF NOT EXISTS ex_official BOOLEAN;
ALTER TABLE pgxnl_eval_runs ADD COLUMN IF NOT EXISTS correct_ex_official INTEGER;
-- 이 문항에서 ReAct 루프 안 가드가 발동한 순서(2026-10-06). 같은 가드가 여러 번이면 여러 번 적힌다.
-- 디버그 모드에서만 보이던 것을 평가에도 남긴다 — "안 듣는 것/발동 안 한 것"을 구분하려고.
-- NULL = 이 열을 넣기 전의 run, 빈 배열 = 발동 없음.
ALTER TABLE pgxnl_eval_items ADD COLUMN IF NOT EXISTS guards_fired TEXT[];
CREATE INDEX IF NOT EXISTS idx_pgxnl_eval_items_run
    ON pgxnl_eval_items (run_id, seq);

-- 벤치마크 정답(gold) 자체가 틀린 문항 등록부. 모델이 옳아도 오답 처리되는 케이스를
-- 결과 화면에 표시해, 개선 작업의 목표에서 제외하고 잘못된 방향으로 튜닝하는 것을 막는다.
-- **EX 계산은 건드리지 않는다** — 화면에 표시와 "결함 제외 EX"를 부가 정보로만 보여준다.
-- (정정 2026-10-06: pgxnl EX 는 리더보드와 같은 기준이 아니다 — 공식은 set 비교라 중복을 무시한다.
--  리더보드와 비교할 값은 correct_ex_official 이다.)
-- question_id로 식별한다(seq는 데이터셋 필터링에 따라 달라지는 위치값이라 불안정하다).
CREATE TABLE IF NOT EXISTS pgxnl_eval_gold_defects (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT        NOT NULL,
    db_id       TEXT        NOT NULL DEFAULT '',
    question_id TEXT        NOT NULL,
    reason      TEXT        NOT NULL,          -- 왜 gold가 틀렸는지 (화면에 표시됨)
    evidence    TEXT,                          -- 근거(측정값, 대조 문항 등)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_name, db_id, question_id)
);

-- 단계별(ReAct/SQL생성/요약/질문보강) 모델 등록부 — 파이프라인의 코드 구간과 LLM 구간이
-- 분리되어 있어, 각 LLM 호출 지점마다 다른 provider/model을 지정할 수 있게 한다.
-- 같은 (provider, model) 조합은 한 번만 등록되도록(중복 관리 방지) UNIQUE 제약을 둔다.
-- API 키는 Fernet 암호화(pgxnl_user_credentials와 동일한 방식)로 저장하고 원문은 절대
-- 조회 응답에 포함하지 않는다.
CREATE TABLE IF NOT EXISTS pgxnl_llm_profiles (
    id                    SERIAL      PRIMARY KEY,
    name                  TEXT        NOT NULL UNIQUE,   -- 표시용 라벨, 기본값은 "provider/model"
    provider              TEXT        NOT NULL,   -- 'anthropic' | 'openai_compatible' | 'watsonx'
    model                 TEXT        NOT NULL,
    base_url              TEXT,
    temperature           REAL        NOT NULL DEFAULT 0.0,
    max_tokens            INTEGER     NOT NULL DEFAULT 16384,
    api_key_enc           TEXT,
    watsonx_project_id    TEXT,
    watsonx_space_id      TEXT,
    watsonx_username      TEXT,
    watsonx_password_enc  TEXT,
    watsonx_instance_id   TEXT,
    watsonx_api_version   TEXT,
    watsonx_verify_ssl    BOOLEAN     NOT NULL DEFAULT true,
    is_default            BOOLEAN     NOT NULL DEFAULT false,  -- 단계 미지정 시 최종 폴백 모델
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, model)
);
-- 기존 설치본 호환 (매 접속 시 실행되어도 안전)
ALTER TABLE pgxnl_llm_profiles ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT false;
-- disable_thinking은 처음엔 모델(프로필) 속성으로 넣었으나, 같은 모델을 단계에 따라
-- (예: react는 사고 필요, enrich_detect는 속도가 중요) 다르게 쓰고 싶다는 지적으로
-- 아래 pgxnl_llm_stage_config 쪽 컬럼으로 옮겼다 — 모델을 중복 등록할 필요가 없어짐.
ALTER TABLE pgxnl_llm_profiles DROP COLUMN IF EXISTS disable_thinking;
-- 부분 유니크 인덱스: is_default=true인 행은 최대 1개만 존재 가능
CREATE UNIQUE INDEX IF NOT EXISTS idx_pgxnl_llm_profiles_one_default
    ON pgxnl_llm_profiles (is_default) WHERE is_default;

-- 파이프라인 단계 -> 등록된 모델 매핑 (관리자, 전체 기본값). profile_id가 NULL이면
-- 등록된 모델 중 is_default=true인 것을(없으면 .env 기반 시스템 기본 모델을) 쓴다.
CREATE TABLE IF NOT EXISTS pgxnl_llm_stage_config (
    stage             TEXT        PRIMARY KEY,  -- 'react' | 'generate_sql' | 'summarize' | 'enrich'
    profile_id        INTEGER     REFERENCES pgxnl_llm_profiles(id) ON DELETE SET NULL,
    -- Qwen3류 하이브리드 reasoning 모델 전용(모델 속성이 아니라 이 단계에서 그 모델을
    -- 어떻게 쓸지의 설정) — 켜면 vLLM에 chat_template_kwargs.enable_thinking=false를
    -- 보내 사고 과정을 건너뛴다. 간단한 모호성 판단(enrich_detect) 같은 단계에서 8분
    -- 넘게 걸리던 게 0.4초로 줄어드는 것까지 실측 확인했다. Qwen 계열이 아닌 모델에는
    -- 무해하게 무시된다. 기본값은 끔(true, 2026-10-20) — thinking 을 켜면 단순 판단도 수십 초가
    -- 걸리고 BIRD 정확도도 오히려 낮았다(실측). 이미 있는 행의 값은 바꾸지 않는다.
    disable_thinking  BOOLEAN     NOT NULL DEFAULT true
);
ALTER TABLE pgxnl_llm_stage_config ADD COLUMN IF NOT EXISTS disable_thinking BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE pgxnl_llm_stage_config ALTER COLUMN disable_thinking SET DEFAULT true;

-- 임베딩 모델 설정(2026-10-20) — 행 하나(id=1). 전엔 .env(PGXNL_EMBEDDING_*, EMBEDDING_API_KEY)에
-- 있었는데 첫 로그인 뒤 관리 화면에서 정하도록 옮겼다. 기동 시 이 행이 없고 .env 에 예전 설정이
-- 있으면 한 번 옮긴다(pgxnl/llm/embedding_config.py). watsonx 는 등록 모델(profile_id)의 연결·자격을 빌린다.
CREATE TABLE IF NOT EXISTS pgxnl_embedding_config (
    id          INTEGER     PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    provider    TEXT        NOT NULL,              -- 'openai_compatible' | 'watsonx'
    model       TEXT        NOT NULL,
    base_url    TEXT,
    verify_ssl  BOOLEAN     NOT NULL DEFAULT true,
    profile_id  INTEGER     REFERENCES pgxnl_llm_profiles(id) ON DELETE SET NULL,
    api_key_enc TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 사용자별 단계 모델 개인 설정("내 설정" 탭) — pgxnl_user_credentials와 같은 오버라이드
-- 패턴: 행이 있으면 그 모델을, 없으면 pgxnl_llm_stage_config(관리자 기본값)을 쓴다.
CREATE TABLE IF NOT EXISTS pgxnl_user_llm_stage_config (
    user_id     INTEGER     NOT NULL REFERENCES pgxnl_users(id) ON DELETE CASCADE,
    stage       TEXT        NOT NULL,
    profile_id  INTEGER     NOT NULL REFERENCES pgxnl_llm_profiles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, stage)
);

-- ── 승인된 사용례 (기존 Query 탐색) ──────────────────────────────────────
-- 수집된 실행 SQL(pgxnl_sql_statements)에 자연어 설명을 붙여 사람이 승인한 것.
-- **시맨틱 캐시(pgxnl_cache)와 소비자가 다르다** — 캐시는 파이프라인이 읽고 같은
-- 질문의 반복을 건너뛰는 용도이고, 이쪽은 사람이 읽고 새 질의를 쓸 때 참고하는
-- 용도다. 그래서 TTL이 없고, 승인 전에는 보이지 않는다.
--
-- 수집 테이블과 따로 두는 이유는 수명이 다르기 때문이다. `수집 초기화`는 대상의
-- 수집 SQL을 통째로 지우는데(SqlStatementStore.delete_target), 사람이 승인해서
-- 설명까지 다듬어 둔 지식이 거기 얹혀 있으면 재수집할 때마다 함께 날아간다.
CREATE TABLE IF NOT EXISTS pgxnl_verified_queries (
    id            BIGSERIAL   PRIMARY KEY,
    target_name   TEXT        NOT NULL,
    schema_name   TEXT        NOT NULL DEFAULT 'public',
    question      TEXT        NOT NULL,   -- describe_sql 이 만들고 사람이 고친 설명
    sql_text      TEXT        NOT NULL,   -- $1,$2 자리표시자는 그대로 둔다(원문 보존)
    sql_hash      TEXT        NOT NULL,   -- 같은 SQL 재등록 방지
    tables_used   JSONB       NOT NULL DEFAULT '[]',
    -- 용어집 PII 플래그로 판정한 값. 승인자가 보고 거르라고 두는 표시이지 차단이
    -- 아니다 — 승인된 항목은 일반 사용자도 보므로, 거르는 판단은 사람이 한다.
    has_pii       BOOLEAN     NOT NULL DEFAULT false,
    approved      BOOLEAN     NOT NULL DEFAULT false,
    approved_by   INTEGER     REFERENCES pgxnl_users(id) ON DELETE SET NULL,
    approved_at   TIMESTAMPTZ,
    created_by    INTEGER     REFERENCES pgxnl_users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- 유사 순위용. pgxnl_cache 의 embedding 과 **쓰임이 다르다** — 저쪽은 임계값을
    -- 넘으면 자동으로 하나를 골라 내보내므로 틀리면 조용한 오답이 되지만(실측: "가장
    -- 적게"가 "가장 많이"에 0.923), 이쪽은 사람이 목록에서 고르므로 임계값이 필요
    -- 없고 순위만 맞으면 된다. 같은 측정이 저쪽에서는 못 쓸 근거였고 여기서는 쓸 근거다.
    embedding     vector(768),
    UNIQUE (target_name, sql_hash)
);
CREATE INDEX IF NOT EXISTS idx_pgxnl_verified_approved
    ON pgxnl_verified_queries (target_name, schema_name, approved);
-- 테이블로 찾는 축이 주(主)다 — 새로 쓰는 사람은 질문이 아니라 테이블을 안다.
CREATE INDEX IF NOT EXISTS idx_pgxnl_verified_tables
    ON pgxnl_verified_queries USING gin (tables_used);
ALTER TABLE pgxnl_verified_queries ADD COLUMN IF NOT EXISTS embedding vector(768);
