# pgxnl 시스템 설계 문서

> LLM 기반 PostgreSQL 자연어 SQL 분석 시스템
> 버전 2.0 (PostgreSQL 전용) · 2026-08

---

## 목차

1. [개요](#1-개요)
2. [설계 원칙](#2-설계-원칙)
3. [시스템 아키텍처](#3-시스템-아키텍처)
4. [질의 처리 흐름](#4-질의-처리-흐름)
5. [컴포넌트 상세](#5-컴포넌트-상세)
   - 5.1 [Orchestrator](#51-orchestrator)
   - 5.2 [질문 보강](#52-질문-보강)
   - 5.3 [메타데이터 레이어](#53-메타데이터-레이어)
   - 5.4 [스키마 링킹 (Schema RAG)](#54-스키마-링킹-schema-rag)
   - 5.5 [ReAct Planner](#55-react-planner)
   - 5.6 [LLM 클라이언트](#56-llm-클라이언트)
   - 5.7 [Agent 도구](#57-agent-도구)
   - 5.8 [SQL Canonicalization](#58-sql-canonicalization)
   - 5.9 [SQL 검증 및 거버넌스 계층](#59-sql-검증-및-거버넌스-계층)
   - 5.10 [문서 지식 레이어](#510-문서-지식-레이어)
   - 5.11 [거버넌스 레이어 (규칙 / 용어집)](#511-거버넌스-레이어-규칙--용어집)
   - 5.12 [캐시 레이어](#512-캐시-레이어)
   - 5.13 [인증 / 보안](#513-인증--보안)
6. [SQL 파서 (ANTLR4)](#6-sql-파서-antlr4)
7. [시스템 DB 스키마](#7-시스템-db-스키마)
8. [환경변수 설정](#8-환경변수-설정)
9. [REST API 요약](#9-rest-api-요약)
10. [구현 로드맵](#10-구현-로드맵)

---

## 1. 개요

pgxnl는 비개발자 또는 SQL에 익숙하지 않은 사용자가 **자연어**로 PostgreSQL
데이터베이스에 질문하면 적절한 SQL을 생성·실행하여 답변하는 시스템입니다.

LLM을 직접 호출하는 단순 프롬프트 방식이 아니라, **도구 호출 기반의 ReAct 에이전트
루프**로 질문 보강 → 스키마 탐색 → SQL 생성 → 검증 → 실행을 수행합니다. 분석 대상은
**PostgreSQL로 한정**하며, 대신 PostgreSQL 네이티브 기능(옵티마이저 통계, 실행 통계,
Row-Level Security)을 최대한 재사용해 별도 인프라 없이도 정확도와 안전성을 확보하는
것을 핵심 설계 목표로 합니다.

### 주요 특징

| 항목 | 설명 |
|---|---|
| **자연어 → SQL** | 사용자 질문으로부터 올바른 SELECT SQL 생성 후 한국어로 설명 |
| **PostgreSQL 전용** | 분석 대상 DB를 PostgreSQL로 한정, 네이티브 기능(pg_stats, pg_stat_statements, RLS)을 적극 재사용 |
| **멀티 LLM** | Anthropic Claude, OpenAI-compatible (vLLM, Ollama) |
| **2단 지식 레이어** | 스키마 메타데이터(§5.3) + 비정형 문서(§5.10)를 별도 레이어로 분리 관리 |
| **거버넌스 내장** | 관리자가 등록하는 SQL 생성 규칙·업무 용어집이 파이프라인 전 단계에 반영 |
| **필수/보조 분리** | 모든 부가 기능(질문 보강, 문서 검색, 캐시 등)은 꺼도 핵심 경로가 그대로 동작 |
| **하이브리드 시맨틱 캐시** | 어휘 유사도(pg_trgm)와 임베딩 유사도(BGE-M3)를 함께 사용 |
| **다층 실행 안전장치** | AST 기반 read-only 강제, RLS 연동, EXPLAIN 기반 비용 추정, 전 요청 감사 로그 |

### 기술 스택

- **Runtime**: Python 3.12, FastAPI, asyncpg (SQLAlchemy 2.0)
- **LLM**: Anthropic Claude / vLLM (OpenAI-compatible)
- **Embedding**: BAAI/bge-m3 (vLLM :8001), 1024차원
- **SQL 파서**: ANTLR4 (PostgreSQL grammar)
- **시스템 DB**: PostgreSQL + pgvector 0.6 + pg_trgm
- **분석 대상 DB**: PostgreSQL (read-only)

---

## 2. 설계 원칙

### 2.1 필수 경로와 보조 컴포넌트의 분리

시스템은 **최소 동작 경로**가 항상 성립해야 합니다.

```
[필수] 사용자 질문 → 스키마 정보 확보 → LLM SQL 생성 → 실행 → 답변
[보조] 질문 보강 · 문서 지식 레이어 · SQL Canonicalization ·
       거버넌스 레이어 · 시맨틱 캐시 · 실행이력 기반 FK 발견
```

모든 보조 컴포넌트는 동일한 인터페이스(`retrieve() → list | None`)를 갖는 Provider로
구현되어, 설정이 없으면 빈 결과를 반환하고 파이프라인 본체는 분기 없이 동작합니다.
각 보조 컴포넌트는 대응하는 환경변수로 개별 on/off가 가능하며 (§8), 기본값은 모두
`false`로 시작해 점진적으로 활성화하는 것을 권장합니다.

### 2.2 LLM 의존 영역과 코드 처리 영역의 분리

| 영역 | 처리 방식 | 근거 |
|---|---|---|
| 모호성 판단, 질문 재작성, SQL 생성, 문서 근거 추출, 결과 요약 | **LLM** | 자연어 이해·생성이 본질적으로 필요 |
| 후보 검색(BM25/임베딩), 값 링킹, 통계 조회, FK 그래프 탐색, SQL 파싱·재작성·검증 | **코드** | 결정론적 처리로 충분하며, LLM보다 빠르고 저렴하고 테스트 가능 |

이 경계는 비용·지연시간 최적화뿐 아니라, LLM 서빙 장애 시에도 코드 영역(스키마 링킹
상당 부분, 값 링킹, Canonicalization, 검증 계층)이 계속 동작해야 한다는 요구사항과
직결됩니다.

### 2.3 확장 가능한 골격 유지

현재는 PostgreSQL만 지원하지만, DB 커넥터·통계 어댑터·SQL 파서 문법을 전부 인터페이스로
분리해두어 향후 다른 DBMS를 다시 지원하게 되더라도 구현체 추가만으로 확장되도록
설계합니다 (§5.3, §6 참고).

---

## 3. 시스템 아키텍처

```
┌─────────────┐    HTTP/SSE    ┌──────────────────────────────────────────┐
│   Browser   │ ◄────────────► │            FastAPI Server :8100           │
│  Web UI     │                │  Auth · SSE · Admin API                   │
└─────────────┘                └───────────────────┬──────────────────────┘
                                                     ▼
                                ┌──────────────────────────────────────────┐
                                │              Orchestrator                 │
                                │  1. 질문 보강 (선택)                       │
                                │  2. 시맨틱 캐시 조회 (선택)                │
                                │  3. 스키마 링킹 (Schema RAG)              │
                                │  4. 문서 지식 레이어 조회 (선택)           │
                                │  5. ReAct 루프 실행                        │
                                │  6. SQL Canonicalization                  │
                                │  7. SQL 검증·거버넌스 계층                 │
                                │  8. 실행 및 캐시 저장                     │
                                └───┬──────────────────────┬───────────────┘
                                    │                      │
                     ┌──────────────▼───────┐   ┌─────────▼──────────────┐
                     │    ReAct Planner     │   │  LLM Provider          │
                     │  Reason→Act→Observe  │◄──►  Anthropic / vLLM     │
                     └──────────────┬───────┘   └────────────────────────┘
                                    │ 도구 호출
                    ┌───────────────┼───────────────┬───────────────┐
                    ▼               ▼               ▼               ▼
             ┌────────────┐ ┌────────────┐ ┌────────────────┐ ┌──────────┐
             │  Schema    │ │    SQL     │ │  Stats/FK      │ │ Document │
             │  Explorer  │ │  Generator │ │  Adapter       │ │ Retriever│
             └─────┬──────┘ └─────┬──────┘ └───────┬────────┘ └────┬─────┘
                   │              │                 │               │
                   ▼              ▼                 ▼               ▼
        ┌───────────────────────────────────────────────────────────────┐
        │                        시스템 PostgreSQL                       │
        │  pgxnl_schema_cache    (DDL/통계 TTL 캐시)                    │
        │  pgxnl_schema_vectors  (pgvector HNSW, M-Schema 포함)         │
        │  pgxnl_document_chunks (pgvector HNSW, 비정형 문서)           │
        │  pgxnl_join_candidates (실행이력 기반 FK 후보)                │
        │  pgxnl_cache           (하이브리드 시맨틱 캐시)                │
        │  pgxnl_rules / pgxnl_glossary (거버넌스 레이어)              │
        │  pgxnl_audit_log       (검증·실행 감사 로그)                  │
        │  pgxnl_users / pgxnl_targets  (메타스토어)                   │
        └───────────────────────────────────────────────────────────────┘

        ┌──────────────────────────────┐   ┌──────────────────┐
        │       Embedding Server       │   │   Target DB       │
        │  BGE-M3 via vLLM :8001       │   │  PostgreSQL       │
        │  1024-dim cosine vectors     │   │  (read-only,      │
        └──────────────────────────────┘   │   RLS 적용 가능)   │
                                            └──────────────────┘
```

### 커넥터 역할 분리

| 커넥터 | 대상 | 권한 |
|---|---|---|
| `target_connector` (`PgConnector`) | 분석 대상 PostgreSQL | `readonly=True` (세션 레벨 가드 + RLS) |
| `system_connector` | 로컬 시스템 PostgreSQL | `readonly=False` (캐시·메타스토어·감사로그 쓰기) |

`target_connector`는 `BaseConnector` 인터페이스를 구현하며, 등록 시 `dialect`가
`postgresql`이 아니면 예외를 던져 현재 지원 범위를 코드 레벨에서 강제합니다. 향후
다른 DBMS를 다시 지원하게 되면 `BaseConnector`의 새 구현체를 추가하는 것만으로
확장됩니다.

---

## 4. 질의 처리 흐름

```
사용자 질문
    │
    ▼
[1] API Key 인증
    │
    ▼
[2] 질문 보강 (PGXNL_ENRICHMENT_ENABLED)
    ├─ 모호성 감지 (패턴 기반 + LLM 판단)
    └─ 비대화형 재작성 (모호성 발견 시)
    │
    ▼
[3] 시맨틱 캐시 조회 (PGXNL_CACHE_ENABLED)
    ├─ pg_trgm 스크리닝 (저비용) → 근접 일치 시 후보로 채택
    ├─ 임베딩 코사인 재조회 (PGXNL_CACHE_EMBEDDING_ENABLED) → 의미적 유사 질문 탐색
    └─ Hit ──► [7] SQL 검증·거버넌스 계층으로 직행 (권한은 매번 재검사)
    │  Miss
    ▼
[4] 스키마 링킹 (Schema RAG)
    질문 임베딩 → pgvector cosine 검색 → Top-K 테이블
    → 경량 표현(검색용)으로 후보 선정 → M-Schema 전체(값 예시 포함) 조립
    → 시스템 프롬프트에 선주입
    │
    ▼
[5] 문서 지식 레이어 조회 (PGXNL_DOCUMENT_STORE_ENABLED)
    질문과 관련된 문서 청크 검색 → 근거로 시스템 프롬프트에 추가
    │
    ▼
[6] 거버넌스 레이어 로드 (규칙 + 용어집 → 시스템 프롬프트 추가)
    │
    ▼
[7] ReAct 루프 (최대 20회 반복)
    ┌─────────────────────────────────────────┐
    │  LLM 호출 (시스템 프롬프트 + 히스토리)   │
    │      │ 도구 선택                          │
    │      ▼                                    │
    │  search_tables / describe_table           │
    │  sample_data / collect_stats               │
    │  generate_sql                              │
    │      │ 결과 히스토리에 추가                │
    │      ▼                                    │
    │  finalize 호출 시 루프 종료                │
    └─────────────────────────────────────────┘
    │
    ▼
[8] SQL Canonicalization (규칙 기반 형태 통일)
    │
    ▼
[9] SQL 검증 및 거버넌스 계층
    파싱 → 카탈로그 바인딩 → 권한 검사(RLS) → 민감 필드 탐지
    → 비용 추정(EXPLAIN) → 판정
    ├─ 거부 ──► 사유 반환 + 감사 로그
    ├─ 수정요청 ──► [7]로 재시도 (문법 오류 루프와 별도)
    └─ 허용 ──► 실행
    │
    ▼
[10] 실행 (읽기전용, 행 제한, timeout)
    │
    ▼
[11] 결과 → 시맨틱 캐시 저장 (SQL 템플릿 단위)
    │
    ▼
[12] SSE 스트림으로 단계별 진행 상황 + 최종 답변 반환
```

---

## 5. 컴포넌트 상세

### 5.1 Orchestrator

**파일**: `pgxnl/agent/orchestrator.py`

시스템의 메인 진입점. 모든 하위 컴포넌트를 조립하고 `analyze()` 메서드로 4절의
전체 흐름을 실행합니다.

#### 생성자 파라미터

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `target_connector` | `PgConnector` | 분석 대상 PostgreSQL 커넥터 (`readonly=True`) |
| `settings` | `Settings` | 환경변수 기반 전체 설정 |
| `system_connector` | `BaseConnector \| None` | 시스템 PG 커넥터. `None`이면 캐시·메타데이터 레이어 전체 비활성 |
| `target_name` | `str` | 캐시·인덱스 격리 키 |
| `schema_cache` | `SchemaCache \| None` | DDL/통계 TTL 캐시 |
| `schema_vector` | `SchemaVectorIndex \| None` | 스키마 임베딩 인덱스 |
| `document_store` | `DocumentStore \| None` | 비정형 문서 지식 레이어 (§5.10) |
| `glossary_store` | `GlossaryStore \| None` | 업무 용어집 (§5.11) |
| `rule_store` | `SqlRuleStore \| None` | SQL 생성/Canonicalization 규칙 (§5.11) |
| `enrichment` | `QuestionEnricher \| None` | 질문 보강 모듈 (§5.2) |

#### 초기화 순서 주의

> `SchemaExplorer`를 먼저 생성한 후 `SchemaVectorIndex`를 생성하여 역참조를
> 주입합니다. 순서가 바뀌면 `AttributeError`가 발생합니다.
> ```python
> self._explorer = SchemaExplorer(...)          # 1. Explorer 먼저
> self._schema_vector = SchemaVectorIndex(...)  # 2. Vector 생성
> self._explorer._vector = self._schema_vector  # 3. 역참조 주입
> ```

#### Lazy 초기화

`_ensure_initialized()`는 첫 `analyze()` 호출 시 한 번만 실행됩니다. 관리 API에서
캐시 통계를 조회할 때는 명시적으로 호출해야 합니다.

---

### 5.2 질문 보강

**파일**: `pgxnl/agent/enrichment.py`

스키마 링킹 이전에 실행되는 경량 전처리 단계로, 모호한 질문을 명확히 하거나 재작성해
이후 단계의 recall과 정확도를 함께 끌어올립니다.

```python
class QuestionEnricher:
    async def enrich(self, question: str) -> EnrichedQuestion:
        ambiguity = self._detect_pattern_ambiguity(question)      # 1차: 정규식, 무료
        if not ambiguity.found and self._semantic_check_enabled:
            ambiguity = await self._detect_semantic_ambiguity(question)  # 2차: LLM 판단
        if not ambiguity.found:
            return EnrichedQuestion(text=question, rewritten=False)
        rewritten = await self._rewrite(question, ambiguity)
        return EnrichedQuestion(text=rewritten, rewritten=True, original=question, reasons=ambiguity.reasons)
```

- **1차(패턴 기반, 코드)**: 날짜/수량 표현 등 알려진 유형을 정규식으로 감지. 비용이
  거의 없어 항상 실행됩니다.
- **2차(의미 기반, LLM)**: 1차가 못 잡는 모호성(기준이 불명확한 비교급/최상급,
  명시 안 된 집계 단위, 여러 컬럼에 해당할 수 있는 지칭 등)을 LLM에게 판단시킵니다.
  질문마다 감지용 LLM 호출이 하나 더 늘어나므로 `PGXNL_ENRICHMENT_SEMANTIC_CHECK_ENABLED=false`가
  기본값이며, 1차에서 이미 모호성을 찾은 경우엔 2차를 건너뜁니다(중복 호출 방지).
  응답은 `AMBIGUOUS: yes|no` / `REASON: ...` 두 줄 고정 형식으로 파싱합니다.
- API 기반 서비스 특성상 초기 구현은 **비대화형 재작성**만 제공합니다. 대화형
  명확화 질문(사용자에게 되묻는 방식)은 SSE 스트리밍 구조와의 통합 설계가 추가로
  필요해 이후 단계에서 검토합니다.
- `PGXNL_ENRICHMENT_ENABLED=false`가 기본값이며, 끄면 질문이 그대로 다음 단계로
  전달됩니다.
- `enrich()`는 `evidence`(예: BIRD 벤치마크의 "Valid charter number means the
  number is not null" 같은 참고 정보)를 `question`과 별도 인자로 받습니다.
  모호성 판단에는 `evidence`를 같이 보여주되(그래야 evidence가 이미 풀어주는
  모호함까지 "모호하다"고 걸려 불필요한 재작성이 발동하는 걸 막을 수 있음),
  재작성 자체는 `question`만 넘겨 evidence가 재작성 과정에서 조용히 사라지는
  걸 방지합니다. 재작성 이후 `evidence`는 `Orchestrator.analyze()`가 다시 붙여
  이후 단계(캐시/스키마 링킹/SQL 생성)로 전달합니다.

**겪은 문제와 교훈**: `question`+`evidence`를 하나의 텍스트로 합칠 때 이어붙이는
**형식**이 SQL 생성 결과 자체를 바꿉니다(실측 확인). `f"{question}\n\n[참고
정보]\n{evidence}"`처럼 헤더로 구조적으로 분리하면, 모델이 "[참고 정보]"를 뺀
순수 질문 부분만 다시 놓고 evidence와 무관한 별개의 모호함까지 찾아내 불필요한
재작성을 더 자주 유발했고, 최종 SQL 생성 단계에서도 (같은 BIRD 문항 기준) RANK()
컬럼 위치가 흔들리는 등 결과 자체가 달라졌습니다. 자연스러운 문장처럼 공백으로만
이어붙인 `f"{question} {evidence}"`가 훨씬 안정적이었습니다 — question/evidence류
텍스트를 합쳐 LLM에 넘겨야 하는 곳이 새로 생기면 구조적 헤더/구분자보다 자연스러운
이어붙임을 먼저 시도할 것.

---

### 5.3 메타데이터 레이어

**파일**: `pgxnl/agent/stats/`, `pgxnl/agent/discovery/`

스키마 구조·통계·테이블 관계를 준비하는 오프라인/배치 성격의 레이어입니다.

#### 통계 어댑터

```python
class StatsAdapter(ABC):
    @abstractmethod
    async def get_column_stats(self, table: str, column: str) -> ColumnStats | None: ...

class PgStatsAdapter(StatsAdapter):
    """PostgreSQL 옵티마이저 통계(pg_stats)를 재사용하는 어댑터."""
    async def get_column_stats(self, table: str, column: str) -> ColumnStats | None:
        row = await conn.fetchrow("""
            SELECT n_distinct, null_frac, most_common_vals, most_common_freqs,
                   histogram_bounds
            FROM pg_stats WHERE tablename = :table AND attname = :column
        """, table=table, column=column)
        return ColumnStats.from_pg_stats(row) if row and row["most_common_vals"] else None
```

`collect_stats` 도구는 `StatsAdapter`를 1차로 조회하고, 값이 없거나 `ANALYZE`가
오래된 경우에만(`pg_stat_user_tables.last_analyze` 확인) 직접 샘플링으로 폴백합니다.
어댑터를 인터페이스로 분리해두어, 향후 다른 DBMS의 통계 카탈로그를 지원하게 되면
새 구현체 추가만으로 확장됩니다.

#### 실행이력 기반 FK 발견

```python
async def discover_joins_from_history() -> list[JoinCandidate]:
    rows = await system_conn.fetch("""
        SELECT query, calls FROM pg_stat_statements
        WHERE query ILIKE '%JOIN%' ORDER BY calls DESC LIMIT 500
    """)
    candidates = []
    for row in rows:
        tree = antlr_parse_postgresql(row["query"])
        visitor = JoinExtractVisitor(weight=row["calls"])
        visitor.visit(tree)  # JOIN ... ON, USING, 암묵적 조인(WHERE 등가조건) 모두 방문
        candidates.extend(visitor.candidates)
    return candidates
```

배치 작업(기본 매일 새벽)으로 실행되어 `pgxnl_join_candidates`에 저장됩니다.
`pg_stat_statements`는 `pg_read_all_stats` 권한이 필요합니다. 명시적 FK 제약이 없는
테이블에서 실사용 조인 패턴을 찾아내는 용도이며, 기본값은 비활성입니다.

#### 스키마 캐시

`pgxnl_schema_cache`가 DDL·통계·목록 조회 결과를 TTL 기반으로 시스템 PG에 영속
저장해 반복적인 카탈로그 조회를 방지합니다 (§7 스키마 참고).

---

### 5.4 스키마 링킹 (Schema RAG)

**파일**: `pgxnl/cache/schema_vector.py`

테이블을 두 가지 표현으로 이중화하여 검색 정밀도와 프롬프트 정보량을 함께 확보합니다.

```python
class SchemaVectorIndex:
    async def build_all(self, tables: list[TableMeta]):
        for t in tables:
            light_doc = f"{t.name}: {t.comment or ''} ({', '.join(c.name for c in t.columns)})"
            embedding = await self._embed_fn(light_doc)
            full_mschema = to_mschema(t)  # 값 예시·PK/FK 포함 전체 M-Schema
            await self._store(t, embedding=embedding, doc=light_doc, mschema=full_mschema)

    async def search(self, question: str, top_k: int) -> list[TableCandidate]:
        qvec = await self._embed_fn(question)
        rows = await conn.fetch("""
            SELECT table_name, mschema FROM pgxnl_schema_vectors
            ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :k
        """, vec=qvec, k=top_k)
        return [TableCandidate.from_row(r) for r in rows]
```

- **경량 표현(`light_doc`)**: 검색 전용, 값 예시를 최소화해 벡터가 "무엇에 관한
  테이블인지"에 집중하도록 함.
- **M-Schema(`full_mschema`)**: 검색된 테이블에 한해 조립되어 SQL 생성 프롬프트에
  전달됨. 값 예시·PK/FK를 모두 포함.
- 인덱스: `HNSW (m=16, ef_construction=64)`, cosine distance (`<=>`).
- **SQLAlchemy 주의**: `text()`에서 `:param::vector` 문법은 파라미터 인식 오류를
  일으키므로 반드시 `CAST(:param AS vector)`를 사용합니다.

#### 인덱싱 시점

| 경로 | 대상 | 방식 |
|---|---|---|
| 실시간 | `describe_table()` 호출 후 | 백그라운드 태스크로 단일 테이블 갱신 |
| 배치 | 관리 UI "스키마 캐시 초기화" | 전체 스키마 재구축 (`build_all`) |

**주의(실시간 갱신의 부작용)**: `describe_table()`이 호출된 테이블만 개별 재임베딩되므로,
사용 패턴에 따라 일부 테이블은 최근 값, 나머지는 과거 값으로 세대가 뒤섞일 수 있습니다.
로컬 임베딩 서버(예: Ollama)는 재계산 시점에 따라 같은 텍스트에도 미세하게 다른 벡터를
낼 수 있어(관측됨), 세대가 섞인 상태에서는 검색 순위가 불안정해질 수 있습니다. 순위가
이상하게 느껴지면 개별 갱신에 의존하지 말고 `DELETE /api/admin/targets/{name}/schema-vector`로
**전체 재색인**해 모든 테이블을 같은 세대로 맞추는 것을 권장합니다.

#### 후보 필터링: top_k + score margin 컷오프

`search(question, top_k, score_margin=...)`(`schema_vector.py`)는 두 단계로 후보를
좁힙니다: ① DB에서 top_k개까지 가져온 뒤, ② `filter_by_score_margin()`로 1위 후보
점수 대비 `PGXNL_SCHEMA_VECTOR_SCORE_MARGIN`(기본 `0.05`) 이내인 것만 남깁니다.
top_k는 상한일 뿐 관련성을 보장하지 않아서 — 예를 들어 스키마에 테이블이 24개면
top_k=10만으로도 질문과 무관한 테이블이 절반 가까이 그대로 프롬프트에 채워지는
문제가 있었고, margin 컷오프는 그중 점수가 확연히 낮은 꼬리를 잘라냅니다. margin을
0으로 두면 기존처럼 top_k 그대로 동작합니다(하위 호환).

**한계 (실측으로 확인, 반드시 알고 사용할 것)**: 이 컷오프는 임베딩 점수 순위가
실제 관련성과 어느 정도 맞아떨어진다는 전제 위에 서 있습니다. 이 전제가 깨지면
정답 테이블이 잘릴 수 있습니다 — 다만 이 컷오프가 틀려도 **정답 자체가 틀려지진
않습니다**: ReAct 루프가 `search_tables`/`describe_table` 도구로 스스로 찾아내는
안전망이 있어(§2.1 필수/보조 원칙), 최악의 경우 도구 호출이 한두 번 늘어나는
정도의 비용만 발생합니다.

`schema_vector_top_k`를 넉넉하게(예: 15~20) 잡아 1차 후보 폭을 넓혀두고, margin으로
2차 컷오프하는 조합을 권장합니다 — top_k는 재현율(recall), margin은 정밀도(precision)
레버라 역할이 다릅니다.

**margin 값은 임베딩 모델의 점수 스케일에 종속적입니다 — 모델을 바꾸면 반드시
재검증하세요.** `dvdrental` 대상, 같은 질문으로 두 임베딩 모델을 실측 비교한 예:

| 질문 | 실제 필요 테이블 | `nomic-embed-text`(로컬 Ollama) | `ibm/granite-embedding-278m-multilingual`(watsonx) |
|---|---|---|---|
| "카테고리별 평균 대여료가 가장 높은 5개는?" | `category`, `film_category`, `film` | `category` 15개 중 **꼴찌**(.408), `film_category` 4위 (3위와 격차 .15) | `film` 1위(.691), `film_category` 2위(.690), `category` 7위(.544) |
| "제일 잘 나가는 배우가 누구야?" | `actor` | 15개 중 9위(.513) | **1위**(.650) |

`nomic-embed-text`는 한국어 질문 ↔ 영문 스키마 교차언어 정렬이 약하고 점수도
0.48~0.58대로 좁게 뭉쳐 있어(margin을 아무리 잘 잡아도 정밀도에 한계), `margin=0.05`
정도로만 완화해 썼습니다. 다국어 모델(`granite-embedding-278m-multilingual`)로
바꾸니 랭킹 품질 자체가 크게 좋아졌고 점수 스프레드도 넓어져(0.43~0.69대)
`margin=0.05`는 오히려 너무 타이트해 필요한 테이블(`category`)까지 잘랐습니다 —
`margin=0.15`로 재보정해서야 필요한 테이블을 살리면서 명백히 무관한 꼬리는 계속
잘라내는 균형을 찾았습니다. **결론: top_k/margin 튜닝보다 근본적인 건 랭킹 품질
자체이고, 한국어처럼 스키마 언어와 질문 언어가 다르면 교차언어 정렬이 강한
임베딩 모델을 쓰는 쪽이 확실한 개선입니다** (아래 "임베딩 provider 선택" 참고).

#### 임베딩 provider 선택: OpenAI 호환 vs watsonx

**파일**: `pgxnl/llm/embeddings.py`, `pgxnl/llm/watsonx_client.py`

`PGXNL_EMBEDDING_PROVIDER`(`openai_compatible` 기본값 | `watsonx`)로 고릅니다.
watsonx는 OpenAI 프로토콜을 안 쓰고 별도 토큰 발급 인증이 필요해(§5.6과 동일한
이유) 전용 분기로 처리합니다. **LLM도 watsonx면 채팅에 쓰는 것과 같은
`WatsonxClient`(이미 인증된 세션)를 그대로 재사용합니다** — `main.py`에서
`create_embed_fn(settings, state.llm)`으로 만들어 `state.embed_fn`에 한 번만
저장해두고, 대상 DB(orchestrator)마다 이 하나를 공유합니다(`api/state.py`). 대상
DB별로 독립적으로 새 클라이언트를 만들면 매번 별도 로그인(토큰 발급) 요청이
생겨 비효율적이기 때문입니다.

**겪은 문제와 교훈 (watsonx 임베딩 전환 과정에서 실측)**:

1. **CPD 인증 필드 우선순위**: `WatsonxClient._get_cpd_token()`이 `WATSONX_API_KEY`가
   설정돼 있으면 `WATSONX_PASSWORD`보다 우선 사용합니다. 계정에 따라 실제로
   유효한 건 API key가 아니라 비밀번호 쪽일 수 있는데(이 경우 API key로 계속
   401), 겉보기엔 "로그인 자체는 되는데 이 앱만 인증 실패"처럼 보여 원인 파악이
   오래 걸렸습니다. CPD 인증이 401로 막히면 **CPD 계정이 API key 인증용인지
   비밀번호 인증용인지부터 직접 두 조합을 다 테스트**해보는 게 빠릅니다 — 서버가
   오래 떠 있으면 예전에 발급받은 토큰을 캐시로 계속 재사용해서 자격증명 문제를
   한동안 감추기도 합니다(재기동해서 새로 토큰을 받아야 할 때 비로소 드러남).
2. **임베딩 모델의 최대 시퀀스 길이**: `ibm/granite-embedding-278m-multilingual`은
   512 토큰 제한이 있어, 컬럼이 매우 많은 테이블(예: BIRD 벤치마크의
   `european_football_2.match`, 컬럼 100개+)의 `light_doc`을 그대로 임베딩하면
   500 오류가 났습니다. `to_light_doc()`(`mschema.py`)이 컬럼을 앞쪽 40개까지만
   포함하도록 캡을 걸어 해결했습니다 — 어차피 검색용 경량 표현은 "테이블이 대략
   뭘 다루는지" 가늠하는 용도라 전체 컬럼이 필요 없습니다.
3. **배치 재색인의 부분 실패 전파**: (2)의 오류가 나기 전엔 `SchemaVectorIndex.build_all()`이
   테이블 하나의 임베딩 실패를 흡수하지 못해 배치 전체가 죽었습니다 — 더 나쁜
   건, `DELETE /api/admin/targets/{name}/schema-vector`가 재구축 **전에** 기존
   벡터를 전부 지우기 때문에, 배치가 중간에 죽으면 실패 지점 이후 스키마들은
   재색인은커녕 기존 데이터도 사라진 채로 남습니다(실제로 BIRD 대상 75개 테이블
   중 24개에서 멈춰 51개가 통째로 빈 상태가 됐습니다). `index_table()`이 이제
   테이블 단위로 실패를 흡수하고 계속 진행하도록 고쳐, 한 테이블의 문제가 나머지
   전체를 막지 않습니다.

---

### 5.5 ReAct Planner

**파일**: `pgxnl/agent/planner.py`

**Reason → Act → Observe** 루프. LLM에게 도구 스키마를 전달하고 도구 호출 결과를
메시지 히스토리에 누적하며 반복합니다.

#### 종료 조건

1. LLM이 `finalize` 도구 호출
2. `stop_reason == "end_turn"`이면서 도구 호출 없음
3. `max_iterations` 초과 (기본 20회)

#### 시스템 프롬프트 구성

```
[기본 분석 절차 + 주의사항]
+ [SQL 생성 규칙 — 번호 매긴 명령문]     ← §5.11 generation_constraint
+ [Few-shot 예시]                        ← §5.11 few_shot
+ [Schema RAG M-Schema 컨텍스트]        ← §5.4
+ [문서 지식 레이어 검색 결과]           ← §5.10, 선택
```

**겪은 문제와 교훈**: 원래는 규칙/few-shot을 "아래 스키마 컨텍스트에 규칙 섹션이
있으면 참고하라"는 간접 참조 방식으로 스키마 목록 **뒤**에 붙였는데, 스키마
목록(특히 컬럼이 많은 테이블 여러 개)이 길면 모델이 뒤에 붙은 규칙을 참고 정보
정도로 취급하고 실제로는 안 지키는 사례가 실측으로 확인됐습니다(예: "RANK()를
마지막 컬럼으로" 규칙이 있는데도 첫 컬럼에 배치). 규칙을 스키마보다 **먼저**,
번호 매긴 명령 목록으로 직접 박아 넣도록 바꾸니 실제로 더 잘 지켜졌습니다 — 다만
그 대가로 규칙 **문구 자체의 정확성**이 훨씬 중요해집니다. 자세한 내용과 규칙
문구 작성 시 주의사항은 §5.11 참고.

---

### 5.6 LLM 클라이언트

**파일**: `pgxnl/llm/__init__.py`

공급자별 클라이언트를 `BaseLLMClient` 인터페이스로 추상화합니다. 메시지 히스토리
포맷 차이(Anthropic `tool_result` 블록 vs OpenAI `role="tool"`)는
`format_assistant_message` / `format_tool_results`가 흡수합니다.

| 클라이언트 | `provider` 값 | 비고 |
|---|---|---|
| `AnthropicClient` | `anthropic` | Rate limit 시 최대 3회 재시도 (tenacity) |
| `OpenAICompatibleClient` | `openai` / `ollama` | vLLM, Ollama 등. `finish_reason` 정규화 |
| `WatsonxClient` | `watsonx` | IBM CPD 배포. 인증/토큰 발급은 §5.4 임베딩 provider 절 참고 |

임베딩 팩토리(`create_embed_fn`)는 Schema RAG·문서 지식 레이어·하이브리드 캐시가
공용으로 사용하는 텍스트 임베딩 함수를 반환합니다. `EMBEDDING_API_KEY`가 미설정이면
관련 기능 전체가 비활성됩니다 (§2.1 원칙).

**겪은 문제와 교훈 (watsonx, 2026-08-20 실측)**:

1. **백틱(`` ` ``)이 있으면 결정론적으로 500 에러**: 이 CPD 배포의 downstream vLLM
   프록시가, 대화의 두 번째 이후 호출(도구 호출 결과가 메시지에 실릴 때)에서 요청
   텍스트에 백틱이 있으면 `"could not decode header"`라는 500을 **매번, 재시도해도
   똑같이** 던지는 걸 확인했다(BIRD 문항 evidence의 마크다운 스타일 강조 —
   `` `Enrollment (K-12)` ``  — 로 재현, 4/4 재현·백틱만 빼면 4/4 성공). 일시적
   장애가 아니라 콘텐츠에 결정론적으로 반응하는 버그라 재시도로는 못 피한다 —
   `WatsonxClient.complete()`가 system_prompt/메시지 전송 직전에 백틱을
   작은따옴표로 치환해 우회한다(`_strip_backticks()`). SQL 생성 의미에 영향 없는
   순수 텍스트 강조 표기라 제거해도 안전하다.
2. **5xx는 최대 2회 재시도**: 위 백틱 버그와는 별개로, 이 CPD 배포가 진짜 일시적
   장애로 5xx를 던지는 사례도 관측됐다(항목마다 매번 다른 trace id, 재현 안 됨) —
   `_MAX_RETRIES=2`, 지수 백오프(1.5s, 3s)로 재시도한다. 4xx(인증/요청 오류)는
   재시도해도 결과가 같으므로 즉시 실패시킨다.

---

### 5.7 Agent 도구

| 도구명 | 설명 |
|---|---|
| `search_tables` | 키워드로 관련 테이블 검색. 결과 SchemaCache에 TTL 캐싱 |
| `describe_table` | 테이블 컬럼 구조·행 수 조회. 캐시 히트 시 DB 쿼리 생략, 조회 후 벡터 인덱스 백그라운드 갱신 |
| `sample_data` | 실제 데이터 샘플 반환 (기본 50행). `StatsAdapter`로 대체 가능한 경우 우선 대체 |
| `collect_stats` | `PgStatsAdapter` 우선 조회, 미비 시 직접 샘플링 폴백 |
| `generate_sql` | 자연어 + 스키마 컨텍스트로 SQL 생성. 오류 시 최대 3회 자기수정 |

`execute_sql`은 도구 목록에서 분리해, ReAct 루프 종료 후 §5.8~5.9를 거친 SQL만
실행되도록 합니다 (기존 설계 대비 변경점 — 검증 없는 즉시 실행 경로를 없애기 위함).

---

### 5.8 SQL Canonicalization

**파일**: `pgxnl/agent/canonicalize.py`

ReAct 루프가 만든 SQL을, 결과는 동일하되 정해진 형태로 강제 변환하는 규칙 기반
후처리 단계입니다. 캐시 저장 전에 반드시 거쳐야 캐시된 SQL의 형태가 일관되게
유지됩니다.

```python
def canonicalize_sql(sql: str, rules: list[CanonRule]) -> str:
    stream = antlr4.InputStream(sql)
    lexer = PostgreSQLLexer(stream)
    tokens = antlr4.CommonTokenStream(lexer)
    tokens.fill()
    tree = PostgreSQLParser(tokens).root()

    rewriter = antlr4.TokenStreamRewriter(tokens)
    for rule in rules:
        rule.apply(tree, rewriter)
    return rewriter.getDefaultText()
```

규칙(`CanonRule`)은 `rule_store`(§5.11)에서 로드합니다. AST를 순회해 위치를 찾고,
실제 텍스트 변경은 `TokenStreamRewriter`로 토큰 스트림에 국소적으로 적용하는 방식을
기본으로 합니다. 규칙이 SELECT 절 구조 자체를 재배열하는 수준으로 복잡해지면 Visitor
기반 전체 재구성으로 전환합니다 (§6 참고).

---

### 5.9 SQL 검증 및 거버넌스 계층

**파일**: `pgxnl/agent/validation.py`

Canonicalization을 거친 SQL이 실행되기 전 마지막으로 통과하는 코드 전용(§2.2) 계층.
전체가 결정론적 로직이며 LLM 호출이 없습니다.

```python
async def validate_and_execute(sql: str, user: User) -> QueryResult:
    tree = antlr_parse_postgresql(sql)
    _assert_read_only(tree)                        # DML/DDL 차단
    _bind_catalog(tree, schema_cache)               # 존재하지 않는 테이블/컬럼 검증
    _check_row_level_policy(tree, user)             # RLS 연동 또는 애플리케이션 레벨 권한 검사
    _flag_sensitive_columns(tree, glossary_store)   # glossary_store의 PII 태그 활용
    plan = await conn.fetch(f"EXPLAIN (FORMAT JSON) {sql}")
    if _estimated_cost_too_high(plan):
        await audit_log.record(sql, user, decision="rejected", reason="cost_exceeded")
        return QueryResult.rejected(reason="비용 초과, 조건을 좁혀 주세요")

    await audit_log.record(sql, user, decision="allowed")
    return await conn.execute(sql, readonly=True, row_limit=..., timeout=...)
```

- **RLS 활용**: PostgreSQL 전용화의 이점입니다. `target_connector` 연결 시 사용자
  역할로 `SET ROLE`을 수행하면, DB 레벨 `CREATE POLICY`가 애플리케이션 레벨 권한
  검사보다 신뢰도 높게 동작합니다.
- **캐시 히트 시에도 이 계층은 반드시 재통과**해야 합니다. 캐시는 SQL 생성만
  건너뛰는 것이지 권한 검사까지 건너뛰면 안 됩니다 (4절 흐름도 참고).
- 거부/허용 여부와 관계없이 모든 판정을 `pgxnl_audit_log`에 기록합니다.

---

### 5.10 문서 지식 레이어

**파일**: `pgxnl/knowledge/document_store.py`

앱 매뉴얼·업무 규정 등 장문 비정형 문서를 청킹·임베딩해 검색하는 레이어로,
컬럼 단위 용어집(§5.11)과는 별도로 관리합니다. 코드값 매핑(용어집 성격)과 서술형
매뉴얼(문서 RAG 성격)은 검색 전략이 달라 하나로 합치면 검색 정밀도가 떨어집니다.

```python
class DocumentStore:
    async def ingest(self, doc_text: str, source: str, target_name: str) -> int:
        chunks = self._chunk(doc_text)  # 섹션/문단 단위
        for chunk in chunks:
            embedding = await self._embed_fn(chunk)
            await self._store(target_name, source, chunk, embedding)
        return len(chunks)

    async def search(self, question: str, target_name: str, top_k: int = 3) -> list[Chunk]:
        qvec = await self._embed_fn(question)
        rows = await conn.fetch("""
            SELECT chunk_text, source FROM pgxnl_document_chunks
            WHERE target_name = :target
            ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :k
        """, target=target_name, vec=qvec, k=top_k)
        return [Chunk.from_row(r) for r in rows]
```

- `pgxnl_schema_vectors`와 동일한 pgvector HNSW 인덱스 구조를 재사용하되 별도
  테이블(`pgxnl_document_chunks`)로 분리해 스키마 벡터와 검색 대상을 구분합니다.
- `document_store=None`이면 완전 비활성 (§2.1 원칙).
- Top-k는 기본 3 이상으로 설정하는 것을 권장합니다. 단일 Top-1만 쓰면 표면적
  유사도 기반 검색에서 정답 청크가 근소한 차이로 밀리는 경우를 놓칠 수 있습니다.
- **스키마 스코핑 미적용 (2026-08-20 확인)**: `pgxnl_document_chunks`에는
  `schema_name` 컬럼이 없습니다 — `pgxnl_cache`/`pgxnl_glossary`와 같은 종류의
  누락(§5.12/§5.11 참고)으로, BIRD처럼 `target_name` 하나에 스키마가 여러 개면
  문서가 다른 스키마로 잘못 검색될 위험이 있습니다. document_store를 실제
  콘텐츠로 채우기 전에 먼저 고쳐야 합니다.
- **DB/catalog 확장은 보류 (2026-08-20 결정)**: DOC/SOC 같은 구조화된 코드-값
  매핑은 document_store(장문 비정형 RAG)가 아니라 glossary_store(§5.11)에
  직접 등록하는 쪽으로 결정했습니다 — 이미 구조화된 데이터는 청킹·임베딩 검색이
  필요 없고, glossary가 이런 용도로 설계돼 있습니다(ADR-0003). document_store는
  진짜 서술형 매뉴얼이 생기면 그때 채웁니다.

---

### 5.11 거버넌스 레이어 (규칙 / 용어집)

**파일**: `pgxnl/governance/`

관리자가 CRUD로 등록하는 두 레지스트리로, 파이프라인 여러 단계에서 참조됩니다.

| 레지스트리 | 내용 | 참조하는 단계 |
|---|---|---|
| `rule_store` (`SqlRuleStore`) | ORDER BY/LIMIT 강제, 금지 테이블, 강제 조인 경로 등 | ReAct 시스템 프롬프트(§5.5), Canonicalization(§5.8) |
| `glossary_store` (`GlossaryStore`) | 업무 용어 ↔ 테이블/컬럼 매핑, PII 태그, 출처(`source`) | 스키마 링킹(§5.4, `_build_schema_context()`가 후보 테이블마다 `[용어집]` 섹션으로 삽입), `describe_table`(§5.7), 검증 계층 민감필드 탐지(§5.9) |

두 스토어 모두 다음 스펙을 만족해야 합니다.

- **스코프**: `target_name` 단위 격리를 기본으로 하되, 전역 규칙 등록도 지원
- **버전관리**: 각 항목에 적용 시점 타임스탬프를 남겨 재현성·감사를 보장
- **우선순위**: 명시적으로 등록된 규칙은 자동 추론 결과(§5.3 FK 발견 등)보다 항상
  우선(override)

CRUD는 관리 API(§9)를 통해 노출됩니다.

`rule_type`은 **어디서 적용되는가**로 갈립니다. 같은 지식이라도 자리가 달라지면
비용과 사정권이 달라지므로, 새 규칙을 만들 때 가장 먼저 정할 것이 이 분류입니다.

| `rule_type` | 적용 시점 | 판정 주체 | 프롬프트 비용 | 늘리는 법 |
|---|---|---|---|---|
| `generation_constraint` | 생성 전(프롬프트) | 모델 | **항상 지불** | 행 추가 |
| `few_shot` | 생성 전(프롬프트) | 모델 | **항상 지불** | 행 추가 |
| `advisory_guard` | ReAct 루프 안 | 코드 | 발동 시만 | 파이썬 클래스 |
| `canonical_rewrite` | 생성 후 | LLM | 없음 | 행 추가 |
| `canonicalization` | 생성 후(마지막) | 파서 | 없음 | 파이썬 클래스 |

생성 후 단계의 실행 순서는 `canonical_rewrite` → `canonicalization`입니다. 코드가
마지막에 오는 이유는, 뒤집으면 코드가 맞춰 놓은 형태(NULL 정렬·별칭·컬럼 순서)를
LLM이 도로 흐트러뜨릴 수 있기 때문입니다.

- `generation_constraint` — 자유 텍스트 규칙 문장. 시스템 프롬프트에 번호 매긴
  명령문으로 직접 삽입합니다(§5.5).
- `few_shot` — `{question, good_sql, bad_sql?, explanation?}`. "항상 X 해라/하지
  마라"류 절대 규칙 문장이 잘 안 먹히는 경계 판단(예: "질문에 명시 안 된 컬럼을
  언제 추가해도 되는가")에는 추상적 규칙보다 구체적 질문+SQL 예시가 더 잘 가르치는
  걸 실측으로 확인했습니다.
- `canonical_rewrite` — `{bad_sql, good_sql, explanation?, when_regex?}`. 생성이
  끝난 SQL을 예시 쌍으로 고칩니다(`agent/canonical_rewrite.py`). `canonicalization`과
  자리는 같고 판정 주체만 다릅니다 — **파서로 판정할 수 있으면 그쪽을 씁니다.**
  이 분류는 파서로는 못 정하는데 SQL만 보면 사람은 아는 변환을 위한 것이고, 코드를
  안 짜고 행 추가만으로 늘릴 수 있다는 게 존재 이유입니다. LLM 재작성은 경계가 없어
  **코드가 검증하고 어긋나면 원본을 씁니다**(참조 테이블 집합과 WHERE/HAVING/조인
  조건의 리터럴 순서열이 같아야 하고, 바뀌어도 되는 것은 SELECT 목록과 컬럼 순서뿐).
  `when_regex`가 안 걸리면 LLM 호출 자체를 하지 않습니다.
  LLM이 **수용되는 변경을 못 내면**(시간 초과·문법 오류·불변식 위반·아예 무변경)
  `definition.kind`가 지정한 파서 규칙이 대신 수행합니다 — 단계를 둘로 나누지 않고
  이 안에서 끝내므로 순서를 고민할 필요가 없고 무엇이 일했는지 한 자리에서 나옵니다.
  `kind`가 없으면 폴백 없이 원본을 씁니다(파서로 판정 불가한 변환). 폴백으로 쓸 수
  있는 종류는 바깥 맥락 없이 만들어지는 것뿐입니다(`dedupe_columns`, `ensure_limit`) —
  스키마나 질문이 필요한 규칙은 맥락이 없으면 조용히 건너뛰어 폴백 구실을 못 합니다.
- `advisory_guard` — 생성된 SQL을 보고 **관찰을 ReAct 루프에 돌려줍니다**(코드가 SQL을
  고치지 않습니다). `definition.kind`로 검사를 고릅니다. 구 분류 `stats_guard`(근거=컬럼
  통계)와 `question_guard`(근거=질문 텍스트)를 합친 것입니다 — 둘을 가르던 축은 사용자에게
  의미가 없었습니다. 하는 일이 같고, 정작 중요한 축은 **고칠 때까지 되돌리는가 vs 질의당
  한 번만 알리는가**인데 그 분류로는 표현되지 않았습니다.
  `SqlRuleStore.list_advisory_guards()`가 신·구 분류를 함께 읽습니다 — 다른 대상 DB에 구
  분류 행이 남아 있어도 동작합니다. **DB 이행과 UI는 2026-09-14에 완료**했습니다
  (행 5건을 `advisory_guard`로 옮기고, 29번에 `kind: "null_ratio"`를 붙여 화면에서
  구분되게 했습니다). `kind`는 `null_ratio`(구 stats_guard) · `ambiguous_column` ·
  `redundant_join` · `column_rationale`(디버그 표시용) · `single_column`(꺼 두기 권장)입니다.

  루프 안에서 도는 검사가 이것만은 아닙니다. **실행하면 반드시 실패하는 SQL**을 되돌리는
  검사 넷(`missing_column`, `alias_scope`, `scalar_subquery`, `window_misuse`)은 코드에
  박혀 있어 규칙으로 끄고 켤 수 없습니다. 조언형은 질의당 한 번만 발동하지만(반복하면
  ReAct가 반복 횟수를 소진합니다) 이 넷 중 셋은 고칠 때까지 매번 되돌립니다.

- `canonicalization` — 파스 트리를 보고 `TokenEdit`으로 고치는 결정론적 변환
  (ADR-0009). `definition.kind`로 구현 클래스를 고릅니다:

  | `kind` | 하는 일 | 추가 인자 |
  |---|---|---|
  | `order_by_nulls` | ORDER BY에 NULLS FIRST/LAST를 붙인다 | `mode`: `desc_last`(기본) \| `sqlite` |
  | `alias_fix` | 잘못 짚은 테이블 별칭을 컬럼 소유 테이블로 고친다 | (스키마 필요) |
  | `column_order` | SELECT 컬럼을 질문에 언급된 순서로 재배열 | `on_conflict`: `skip`(기본) \| `evidence` \| `question` |
  | `canonical_column` | 사본 컬럼을 정본 컬럼으로 바꾼다 | `aliases`, `rewrite` |
  | `dedupe_columns` | SELECT의 완전 중복 컬럼을 마지막 하나만 남긴다 | 없음 |
  | `ensure_limit` | LIMIT 없는 SELECT에 기본 LIMIT을 붙인다 | `default_limit` |

  어느 규칙이 **실제로 편집을 냈는지**는 `canonicalize_sql_verbose()`가 돌려주고
  디버그에 `[정규화] 적용 규칙: DedupeColumnsRule(id 42)` 로 찍힙니다. 규칙을 뺄지
  판단하려면 "등록돼 있었다"가 아니라 "일했다"를 세야 하기 때문입니다. `CanonRule`의
  `source_rule_id`가 `pgxnl_rules.id`와 이어 줍니다.

**어느 자리에 둘지 고르는 기준**: "만들어진 SQL만 보고 판정되는가?" 된다면 뒤(생성
후)에 둡니다. 예외를 프롬프트 앞에 두면 **모든 질의에서 저울질이 일어나** 무관한
문항이 깨집니다 — 2026-09-10 실측: BIRD 465용 지식을 few-shot으로 앞에 두자 465는
얻었지만 444·447·452를 잃었고(EX 28 → 26), 같은 지식을 `canonicalization`으로
내리자 465를 얻고 손실이 0이었습니다(EX 29). 깨진 셋은 few-shot 내용과 논리적
관계가 없습니다 — 내용 충돌이 아니라 텍스트가 늘어서 흔들린 것입니다.

**규칙 문구 작성 시 겪은 문제와 교훈**:

1. **완곡한 표현은 "선택"으로 읽힌다**: "ORDER BY는 필요없습니다" 같은 완곡체는
   모델에게 "안 써도 그만"으로 해석돼 계속 위반하는 사례가 있었습니다. 금지를
   의도한 규칙은 반드시 "~하지 마세요"류 명시적 금지형으로 쓸 것 — §5.5에서
   규칙을 프롬프트 앞쪽에 salient하게 배치하도록 바꾼 뒤로 이 차이가 더 뚜렷하게
   드러났습니다(약하게 배치돼 있을 땐 모호한 문구가 무시돼서 티가 안 났을 뿐).
2. **단일 문항 기준 반복 조정 = 암기, 일반화 아님**: 특정 BIRD 문항 하나에서
   관찰된 실패(예: "부모 테이블 JOIN 시 원치 않는 컬럼이 붙는다")를 고치겠다고
   그 문항 하나로만 반복 검증하며 규칙 문구를 점점 더 구체적으로("JOIN 키
   컬럼(cdscode)도 넣지 마라") 다듬었더니, 그 문항은 좋아졌다 나빠졌다 했지만
   **다른 문항에 미치는 영향은 전혀 보지 못했고**, 실제로 문구를 더 구체화할수록
   그 문항이 요구하는 다른 컬럼(예: 집계값)까지 함께 빠지는 부작용이 나왔습니다.
   규칙/프롬프트를 바꿀 때는 반드시 같은 스키마의 여러 문항(BIRD 평가 기준
   최소 10문항 이상 배치)으로 전후 비교할 것 — 문항 하나만 보고 규칙을 튜닝하지
   말 것. 구체적 값/컬럼명을 규칙 문구에 직접 넣는 것도 피할 것(일반화된 원칙으로
   표현).

#### 실행하면 반드시 실패하는 SQL을 미리 잡는다 (2026-09-03)

**파일**: `agent/validation.py`(`window_misuse_clause`), `agent/orchestrator.py`
(`_generate_sql` ReAct 핸들러)

검증 계층(§5.9)의 검사에는 두 종류가 있고, **실패 시 방향이 반대**입니다.

| 종류 | 예 | 판단 불가일 때 |
|---|---|---|
| 거버넌스(권한/PII) | `_flag_sensitive_columns` | **거부** — 보안 게이트는 못 본 것을 통과시키면 안 됨 |
| 실행 가능성 | `_bind_columns`, `window_misuse_clause` | **통과** — 조회 실패는 거부 사유가 아님 |

`window_misuse_clause()`는 WHERE / GROUP BY / HAVING / JOIN ... ON에서 윈도우
함수(`OVER`)를 찾습니다. PostgreSQL은 이 절들이 **끝난 뒤** 윈도우 함수를 계산하므로
그 안에서 참조할 수 없습니다. SELECT와 ORDER BY, 서브쿼리 안의 윈도우 함수는 정상이라
잡지 않습니다 — 과잉 차단은 정상 질의를 죽입니다.

**중요한 건 이 검사를 어디에 두느냐입니다.** 검증 계층은 ReAct 루프가 **끝난 뒤**
동작해서, 거기서 거부하면 모델이 고칠 기회가 없습니다(실측: BIRD seq 454가 8개 run
내내 같은 SQL로 실패). 그래서 같은 검사를 `_generate_sql` 핸들러 안에도 두고, 고치는
방법(서브쿼리로 감싸 별칭으로 필터)을 **관찰 결과로 돌려줍니다.** 그러자 모델이 스스로
정답 형태를 만들었습니다.

일반화하면: **"실행하면 반드시 실패한다"고 코드가 확신할 수 있는 SQL은 루프 안에서
고칠 방법과 함께 돌려준다.** 루프 밖의 거부는 최후의 방어선이지 교정 수단이 아닙니다.
`_check_question_literals`(질문 리터럴 변형 되돌리기)가 같은 자리에 같은 이유로 있습니다.

#### 용어집 관련성 필터와 등록 시점 정규화 (2026-09-03)

**파일**: `pgxnl/governance/glossary_terms.py` (순수 함수), `orchestrator._glossary_relevant`
(사용 시점), `routes_admin` glossary CRUD (등록 시점)

후보 테이블에 등록된 용어집 항목이 늘수록 질문과 무관한 정의까지 매번 전부
schema_context에 실립니다. 이를 거르는 필터가 있었지만 **기본값이 "포함"이라 사실상
동작하지 않았습니다** — 정의문에 "코드=값" 나열이 없으면 무조건 통과시켰는데, 서술형으로
길게 쓴 항목일수록 그 쌍이 없어서 그냥 빠져나갔습니다. 실측(2026-09-03) 결과 13개 중
10개가 30문항 전부에서 통과해 schema_context의 43%(질문당 1,761자)가 무관한 용어집이었습니다.

기본값을 **"제외"**로 뒤집고, 질문에 문자 그대로 등장하는 두 단서만 봅니다(ADR-0003에
따라 임베딩 검색은 붙이지 않습니다):

1. **별칭** — `term`/`column_name`을 쉼표로 나눈 각 표현. 낱말 단위 전체 포함, 순서 무시.
2. **값 라벨** — `Values: A, B, C` 나열과 `31=State Special Schools` 코드=값 표기 양쪽.

결과는 질문당 평균 **1,761자 → 109자(94% 감소)**. 용어집은 보조 컴포넌트이므로(설계
원칙 1) 빠져도 ReAct가 `describe_table`로 스키마를 볼 수 있습니다 — 과잉 포함보다 과소
포함이 안전합니다.

**신호 설계에서 막은 오탐 두 가지** (둘 다 실측):

- 코드 자체(`31`, `54`)는 신호로 쓰지 않습니다. 두 자리 숫자는 너무 약해서 seq 452의
  날짜 `12/31/1980`이 DOC의 코드 `'31'`에 걸렸습니다. 값을 코드로 지칭하는 질문은
  evidence에서 `DOC = 31`처럼 약어를 함께 쓰므로 별칭 신호로 이미 잡힙니다.
- 나열은 쉼표로만 끊습니다. `/`로도 끊었더니 `98=Regional Occupational Center/Program`이
  `Program` 한 단어로 쪼개져 seq 465의 "magnet program"에 걸렸습니다 — 값 라벨의
  일부만 떼어내면 그건 더 이상 그 값을 가리키지 않습니다.

**등록 시점 정규화·진단이 필수인 이유**: 기본값을 "제외"로 뒤집으면 새로운 실패 모드가
생깁니다 — 예전에는 서술형으로 아무렇게나 등록해도 무조건 실렸지만, 이제는 신호가 없으면
**조용히 한 번도 안 실립니다.** 등록은 성공했는데 아무 효과가 없는 상태가 제일 나쁩니다.
그래서 판정 규칙을 `glossary_terms`에 모아 **등록 시점과 사용 시점이 같은 규칙을 보게**
하고, CRUD API가 두 가지를 합니다:

- `normalize_definition()` — 되돌릴 수 있는 표기 차이만 기계적으로 흡수합니다(공백 정리,
  `값:` → `Values:`, 쉼표가 없고 ` / `로만 나뉜 나열을 쉼표로 통일, 값의 겉따옴표 제거).
  서술을 값 나열로 바꾸는 건 뜻을 바꾸는 일이라 자동화하지 않습니다.
- `diagnose()` — 그 항목이 어떤 별칭/값으로 걸리는지, 아예 안 걸리는지를 돌려줍니다.
  등록을 막지는 않고(관리자가 의도적으로 좁게 등록할 수 있음) 경고만 하며, 목록 화면에도
  `✕ 어떤 질문에도 안 실림` / `⚠ 신호 약함` 배지로 표시합니다.

**정의문 작성 관례** (필터가 이 관례를 전제로 동작합니다):

- 값 나열은 `Values: A, B, C` 형태로. 예제와 서술은 빼고 200자 이하로.
- 등록어가 컬럼명 그대로(`GSoffered`)면 자연어 질문에 절대 안 걸립니다 —
  `GSoffered, grade span offered`처럼 자연어 표현을 쉼표로 덧붙일 것.

#### glossary_store를 schema_context에 직접 연결 (2026-08-20)

원래 `glossary_store`는 `describe_table` 도구(§5.7)를 명시적으로 호출할 때만
노출됐는데, §5.5의 시스템 프롬프트가 "schema_context에 이미 있는 테이블은
describe_table을 다시 부르지 마라"고 유도하면서 이 경로가 사실상 죽어있었습니다.
스키마 벡터 검색(§5.4)이 뽑은 후보 테이블은 DB catalog의 `obj_description`/
`col_description`(§5.4 인접 §3 M-Schema)만 schema_context에 실렸는데, 이 값이
비어있는 DB(예: BIRD처럼 CSV 일괄 임포트로 만들어진 DB)에서는 컬럼명 외에 아무
힌트가 없었습니다.

`_build_schema_context()`(`orchestrator.py`)가 후보 테이블마다
`glossary_store.for_table()`을 직접 호출해 `[용어집]` 섹션으로 붙이도록
고쳤습니다 — describe_table 호출 여부와 무관하게 항상 노출됩니다.

**출처 필드 추가**: `pgxnl_glossary`에 `source TEXT`(nullable) 컬럼을 추가해
각 항목이 어느 외부 문서에서 왔는지 URL/문서명으로 남깁니다. 원본 문서 전체를
별도 저장소(document_store)에 들고 있지 않기로 했습니다 — 코드-값 매핑처럼
구조화된 지식은 검색(RAG) 대상이 아니라 glossary 항목 자체가 최종 형태이므로,
출처 추적성만 있으면 충분합니다(문서 원문 보관은 §5.10에서 다시 검토 예정,
ADR-0003의 "후속 검토" 참고).

**실측 결과 (BIRD california_schools, 30문항)**: 캘리포니아 교육부(CDE)
공식 데이터 딕셔너리(`data.sandiegodata.org`의 CDE 미러 — 원본
`cde.ca.gov/Ds/si/ds/fspubschls.asp`는 WAF로 자동 접근 차단됨)에서 DOC/SOC/
EdOpsCode/GSoffered/GSserved/FundingType/Virtual/Magnet/StatusType 9개 필드
정의를 확보해 `schools` 테이블에 등록한 뒤 재평가한 결과, EX가 **30%(9/30) →
36.67%(11/30)**로 개선됐습니다. 애초 이 작업의 동기가 됐던 문항("merged Unified
School District" vs "Elementary School District" 판단에 `DOC=54`/`DOC=52`
코드가 필요한 케이스)은 코드 해석 자체는 정확해졌지만, 별개의 필터 범위 버그로
여전히 실패 — glossary 부재로 인한 실패와 다른 원인의 실패를 구분하는 데도
이 실측이 도움이 됐습니다. `Magnet` 필드는 CDE 문서상 "Y/N 텍스트"로 설명되지만
실제 BIRD DB 컬럼은 `integer` 타입 `0/1` 값으로 저장돼 있어 문서-데이터 드리프트
사례로 glossary 정의에 명시해뒀습니다.

---

### 5.12 캐시 레이어

#### 스키마 캐시 (`pgxnl_schema_cache`)

DDL·통계·목록 조회 결과를 시스템 PG에 TTL 기반으로 영속 저장합니다 (기본 24시간,
`PGXNL_SCHEMA_CACHE_TTL`). 관리 UI에서 target별 개별 초기화가 가능합니다.

#### 하이브리드 시맨틱 캐시 (`pgxnl_cache`)

```python
async def lookup(question: str, target_name: str) -> CacheEntry | None:
    trgm_hit = await self._trgm_lookup(question, target_name, threshold=0.85)  # 1차: 저비용 스크리닝
    if trgm_hit:
        return trgm_hit
    if not self._embedding_enabled:
        return None
    embedding = await self._embed_fn(question)
    return await self._embedding_lookup(embedding, target_name, threshold=0.90)  # 2차: 의미 기반
```

- 1차는 `pg_trgm` 어휘 유사도로 완전/근접 일치를 저비용에 스크리닝합니다.
- 2차(`PGXNL_CACHE_EMBEDDING_ENABLED`)는 Schema RAG와 동일한 BGE-M3 임베딩을
  재사용해 표현이 달라도 의미가 같은 질문을 찾습니다.
- 캐시에는 **SQL 템플릿**(리터럴 파라미터화)을 저장하며, 원시 실행 결과는 저장하지
  않습니다 — 데이터 자체가 계속 바뀌기 때문입니다.
- `target_db`로 격리되며, 기본 TTL 24시간.
- **캐시 히트는 §5.9(검증 계층) 재통과를 생략하지 않습니다** — 하이브리드 전환과
  무관하게 이 원칙은 고정입니다.

#### 스키마 벡터 인덱스

§5.4 참고. `pgxnl_schema_vectors`, HNSW(m=16, ef_construction=64), cosine distance.

---

### 5.13 인증 / 보안

**파일**: `pgxnl/auth/`

| 항목 | 구현 |
|---|---|
| API Key 저장 | bcrypt 해시(`api_key_hash`) + AES-256 암호화 원본(`api_key_enc`) 이중 보관 |
| 비밀번호 | PBKDF2-HMAC-SHA256 기반 해시(`salt:hash`) |
| DB 자격증명 | AES-256(Fernet) + `SECRET_KEY`로 암호화하여 시스템 DB 저장 |
| Read-only 가드 | ① ANTLR AST 파싱으로 DML/DDL 차단(애플리케이션 레벨) ② `SET TRANSACTION READ ONLY`(DB 레벨) ③ RLS(§5.9) |
| 역할 | `admin`(전체 관리), `user`(분석만) |
| API Key 전달 | `X-API-Key` 헤더 또는 `?api_key=` 파라미터(SSE/EventSource) |

---

## 6. SQL 파서 (ANTLR4)

pgxnl의 파싱·검증·재작성 로직(§5.3 FK 발견, §5.8 Canonicalization, §5.9 검증
계층)은 전부 **ANTLR4 (PostgreSQL grammar)**로 통일합니다.

**선택 근거**: 향후 다른 DBMS를 다시 지원하게 될 가능성을 열어두기 위해, grammar
교체만으로 확장 가능한 파서를 표준으로 채택합니다. 순수 생성 코드라 C 바인딩 없이
배포·관리가 단순하다는 것도 실무적 이점입니다.

### SQL 재생성(deparse) 전략

ANTLR은 "AST를 넘기면 완성된 SQL 문자열이 나오는" 내장 deparse 함수는 없지만,
Visitor/Listener로 AST를 순회하며 SQL을 재조립하는 것은 표준적으로 쓰이는 방법입니다.
규칙의 성격에 따라 두 방식을 나눠 씁니다.

| | TokenStreamRewriter (국소 patch) | Visitor/Listener 전체 재구성 |
|---|---|---|
| 방식 | 원본 토큰 스트림 유지, 바뀌는 부분만 삽입/치환/삭제 | AST 전체를 순회하며 SQL을 처음부터 재조립 |
| 구현 비용 | 낮음 | 높음 — 사실상 자체 deparser 구현 |
| 원본 보존 | 건드리지 않은 부분은 원본 그대로(공백·줄바꿈·주석 포함) | 항상 균일한 스타일로 새로 출력 |
| 적합한 경우 | LIMIT 삽입, ORDER BY 재배치 등 §5.8의 국소적 patch | SELECT 절 컬럼 재배열, 서브쿼리 삽입 등 구조적 변경 |

현재 §5.8의 규칙 셋은 국소적 patch 범위이므로 **TokenStreamRewriter로 시작**하고,
규칙이 구조적 변경까지 다뤄야 할 정도로 복잡해지면 Visitor 기반 전체 재구성으로
전환합니다.

---

## 7. 시스템 DB 스키마

모든 테이블은 시스템 PostgreSQL(`pgxnl` DB, `public` 스키마)에 생성됩니다.

```sql
-- 사용자
CREATE TABLE pgxnl_users (
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

-- 스키마 캐시 (DDL/통계/목록)
CREATE TABLE pgxnl_schema_cache (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT        NOT NULL,
    cache_key   TEXT        NOT NULL,   -- ddl: / tables: / search: / stats:
    data        JSONB       NOT NULL,
    cached_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_name, cache_key)
);
CREATE INDEX idx_pgxnl_schema_cache_lookup ON pgxnl_schema_cache (target_name, cache_key);

-- 스키마 벡터 인덱스 (경량 표현 + M-Schema)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE pgxnl_schema_vectors (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT        NOT NULL,
    schema_name TEXT        NOT NULL,
    table_name  TEXT        NOT NULL,
    doc         TEXT        NOT NULL,      -- 경량 표현 (임베딩 원문)
    mschema     JSONB       NOT NULL,      -- 값 예시 포함 전체 M-Schema
    embedding   vector(1024),
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (target_name, schema_name, table_name)
);
CREATE INDEX idx_pgxnl_schema_vectors_hnsw
    ON pgxnl_schema_vectors USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 문서 지식 레이어
CREATE TABLE pgxnl_document_chunks (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    chunk_text  TEXT        NOT NULL,
    embedding   vector(1024),
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pgxnl_document_chunks_hnsw
    ON pgxnl_document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 실행이력 기반 FK 후보
CREATE TABLE pgxnl_join_candidates (
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

-- 하이브리드 시맨틱 캐시
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE pgxnl_cache (
    id          SERIAL      PRIMARY KEY,
    target_db   TEXT        NOT NULL,
    question    TEXT        NOT NULL,
    answer      TEXT        NOT NULL,
    sql_steps   JSONB       NOT NULL DEFAULT '[]',
    embedding   vector(1024),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hit_count   INTEGER     NOT NULL DEFAULT 0
);
CREATE INDEX idx_pgxnl_cache_trgm ON pgxnl_cache USING GIN (question gin_trgm_ops);
CREATE INDEX idx_pgxnl_cache_target ON pgxnl_cache (target_db, created_at DESC);

-- 거버넌스: SQL 생성 규칙
CREATE TABLE pgxnl_rules (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT,                       -- NULL이면 전역 규칙
    rule_type   TEXT        NOT NULL,       -- canonicalization | canonical_rewrite |
                                            -- generation_constraint | few_shot |
                                            -- question_guard | stats_guard
    definition  JSONB       NOT NULL,
    enabled     BOOLEAN     NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 거버넌스: 업무 용어집
CREATE TABLE pgxnl_glossary (
    id          SERIAL      PRIMARY KEY,
    target_name TEXT,
    term        TEXT        NOT NULL,
    table_name  TEXT,
    column_name TEXT,
    definition  TEXT        NOT NULL,
    is_pii      BOOLEAN     NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 감사 로그
CREATE TABLE pgxnl_audit_log (
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
CREATE INDEX idx_pgxnl_audit_log_target_time ON pgxnl_audit_log (target_name, created_at DESC);
```

---

## 8. 환경변수 설정

prefix: `PGXNL_` (일부 예외).

### LLM

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_LLM_PROVIDER` | `anthropic` | `anthropic \| openai \| ollama` |
| `PGXNL_LLM_MODEL` | `claude-sonnet-4-20250514` | LLM 모델명 |
| `PGXNL_LLM_BASE_URL` | — | vLLM 엔드포인트 |
| `PGXNL_LLM_TEMPERATURE` | `0.0` | 0.0 ~ 1.0 |
| `PGXNL_LLM_MAX_TOKENS` | `4096` | 응답 최대 토큰 수 |

### Schema RAG / 임베딩

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_EMBEDDING_PROVIDER` | `openai_compatible` | `openai_compatible` \| `watsonx`. watsonx면 LLM과 세션 공유 (§5.4) |
| `EMBEDDING_API_KEY` | — | `openai_compatible`일 때만 사용. `dummy`면 임베딩 관련 기능 전체 비활성 |
| `PGXNL_EMBEDDING_BASE_URL` | `https://api.openai.com/v1` | 임베딩 서버 엔드포인트 (`openai_compatible` 전용, watsonx는 `PGXNL_LLM_BASE_URL` 재사용) |
| `PGXNL_EMBEDDING_MODEL` | `text-embedding-3-small` | 임베딩 모델명 |
| `PGXNL_EMBEDDING_DIMENSIONS` | `1536` | 벡터 차원수. `db/schema.sql`의 `vector(N)`과 일치해야 함 |
| `PGXNL_SCHEMA_VECTOR_ENABLED` | `true` | Schema RAG 활성화 |
| `PGXNL_SCHEMA_VECTOR_TOP_K` | `10` | 검색 반환 테이블 수 (1차 상한, recall 레버) |
| `PGXNL_SCHEMA_VECTOR_SCORE_MARGIN` | `0.05` | 1위 후보 점수 대비 이 마진 밖인 후보 컷오프 (2차, precision 레버). `0`이면 비활성. 임베딩 모델 바꾸면 재검증 필요 (§5.4) |

### 질문 보강

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_ENRICHMENT_ENABLED` | `false` | 질문 보강 단계 활성화 |
| `PGXNL_ENRICHMENT_SEMANTIC_CHECK_ENABLED` | `false` | 패턴 기반으로 못 잡는 모호성을 LLM으로 2차 판단 (질문당 LLM 호출 1회 추가) |

### SQL Canonicalization / 검증

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_CANONICALIZATION_ENABLED` | `true` | Canonicalization 활성화 |
| `PGXNL_VALIDATION_MAX_COST` | `100000` | EXPLAIN 비용 임계값 |
| `PGXNL_AUDIT_LOG_ENABLED` | `true` | 감사 로그 활성화 |

### 문서 지식 레이어

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_DOCUMENT_STORE_ENABLED` | `false` | 문서 지식 레이어 활성화 |
| `PGXNL_DOCUMENT_CHUNK_SIZE` | `500` | 청크 크기(문자 수) |
| `PGXNL_DOCUMENT_TOP_K` | `3` | 검색 반환 청크 수 |

### 실행이력 기반 FK 발견

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_JOIN_DISCOVERY_ENABLED` | `false` | 배치 활성화 |
| `PGXNL_JOIN_DISCOVERY_SCHEDULE` | `0 3 * * *` | 배치 실행 주기 |

### Agent

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_AGENT_MAX_ITERATIONS` | `20` | ReAct 루프 최대 반복 |
| `PGXNL_AGENT_MAX_CORRECTIONS` | `3` | SQL 자기수정 최대 횟수 |
| `PGXNL_AGENT_SAMPLE_ROWS` | `50` | `sample_data` 기본 행 수 |
| `PGXNL_AGENT_STATS_TOP_N` | `20` | `collect_stats` 상위 값 수 |
| `PGXNL_AGENT_MAX_CONTEXT_TABLES` | `15` | LLM 컨텍스트 최대 테이블 수 |

### 캐시

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_SCHEMA_CACHE_TTL` | `86400` | DDL/통계 캐시 TTL(초) |
| `PGXNL_CACHE_ENABLED` | `true` | 시맨틱 캐시 활성화 |
| `PGXNL_CACHE_SIMILARITY_THRESHOLD` | `0.85` | pg_trgm 캐시 히트 임계값 |
| `PGXNL_CACHE_EMBEDDING_ENABLED` | `false` | 임베딩 기반 2차 캐시 조회 활성화 |
| `PGXNL_CACHE_EMBEDDING_THRESHOLD` | `0.90` | 임베딩 캐시 히트 임계값 |
| `PGXNL_CACHE_TTL_SECONDS` | `86400` | 시맨틱 캐시 TTL(초) |

### 시스템 DB

| 환경변수 | 설명 |
|---|---|
| `PGXNL_SYSTEM_PG_DSN` | 시스템 PostgreSQL DSN |
| `PGXNL_SYSTEM_PG_USER` | DB 사용자 |
| `PGXNL_SYSTEM_PG_PASS` | DB 비밀번호 |
| `PGXNL_PG_POOL_SIZE` | 커넥션 풀 크기(기본 10) |
| `PGXNL_PG_MAX_OVERFLOW` | 풀 초과 허용 수(기본 20) |

### API 서버

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `PGXNL_API_HOST` | `0.0.0.0` | 바인드 주소 |
| `PGXNL_API_PORT` | `8100` | 포트 번호 |
| `PGXNL_API_WORKERS` | `4` | uvicorn 워커 수 |
| `PGXNL_LOG_LEVEL` | `info` | 로그 레벨 |
| `PGXNL_SECRET_KEY` | — | DB 자격증명 암호화 키(반드시 교체) |
| `PGXNL_ADMIN_INITIAL_PASSWORD` | `passw0rd` | admin 계정 초기 비밀번호 |

---

## 9. REST API 요약

모든 API 호출에 `X-API-Key: {api_key}` 헤더 필요. EventSource(SSE)는 헤더 불가이므로
`?api_key={api_key}` 쿼리 파라미터 사용.

### 인증

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/auth/login` | 로그인 → `api_key` 반환 |
| `GET` | `/api/me` | 내 프로필 조회 |

### 분석

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` | `/api/targets` | 분석 가능한 대상 DB 목록 |
| `POST` | `/api/analyze` | 자연어 질문 분석 (SSE 스트리밍) |

### 관리 (admin 전용)

| 메서드 | 경로 | 설명 |
|---|---|---|
| `GET` / `PUT` / `DELETE` | `/api/admin/targets/{name}` | 대상 DB 등록/수정/삭제 |
| `DELETE` | `/api/admin/targets/{name}/schema-cache` | 스키마 캐시 초기화 + 벡터 재구축 트리거 |
| `GET` | `/api/admin/schema-cache/stats` | 스키마 캐시 통계 |
| `GET` / `DELETE` | `/api/admin/targets/{name}/schema-vector` | 벡터 인덱스 통계 / 초기화 |
| `GET` / `DELETE` | `/api/admin/semantic-cache` | 시맨틱 캐시 통계 / 초기화 |
| `GET` / `POST` / `PUT` / `DELETE` | `/api/admin/rules` | SQL 생성 규칙 CRUD |
| `GET` / `POST` / `PUT` / `DELETE` | `/api/admin/glossary` | 업무 용어집 CRUD |
| `POST` / `GET` / `DELETE` | `/api/admin/targets/{name}/documents` | 문서 지식 레이어 등록/조회/삭제 |
| `GET` | `/api/admin/audit-log` | 감사 로그 조회 (필터: target/user/decision/기간) |
| `GET` / `PUT` | `/api/admin/settings` | LLM 설정 조회/변경 |
| `GET` / `POST` | `/api/admin/users` | 사용자 목록/생성 |

---

## 10. 구현 로드맵

| 순서 | 작업 | 근거 |
|---|---|---|
| 1 | PostgreSQL 전용 커넥터·ANTLR grammar 확정 | 이후 모든 작업의 전제 |
| 2 | `execute_sql`을 검증 계층 뒤로 이동 + 캐시 히트 시 권한 재검사 강제 | 보안 공백 가능성이 있어 최우선 |
| 3 | SQL Canonicalization (TokenStreamRewriter 기반) | 구현 비용 낮고 캐시 일관성에 직결 |
| 4 | `PgStatsAdapter` 도입 (`collect_stats` 개선) | 기존 로직 대체, 비용 절감 즉시 체감 |
| 5 | 스키마 링킹 경량 표현/M-Schema 이중화 | ReAct 반복 횟수 절감 기대 |
| 6 | 문서 지식 레이어 (`DocumentStore`) | 실제 검증 완료, 후보 신뢰도 있음 |
| 7 | 거버넌스 레이어 CRUD API + 스코프/버전관리 보강 | 규칙·용어집 운영 편의성 |
| 8 | 실행이력 기반 FK 발견 (배치) | 우선순위 낮음, 명시적 FK 있는 스키마면 효과 제한적 |
| 9 | 질문 보강 (비대화형 재작성) | 효과 측정 후 확장 여부 결정 |
| 10 | 캐시 하이브리드(임베딩) 전환 | pg_trgm 단독 성능 데이터 확보 후 A/B 비교 |

모든 신규 기능은 기본값 비활성으로 시작해, 기존 동작을 깨지 않고 점진적으로 켜는
것을 원칙으로 합니다.
