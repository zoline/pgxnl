# pgxnl 0.5

**SQL을 모르는 사람이 PostgreSQL에 자연어로 묻고 답을 받는 도구.**
LLM이 질문을 SQL로 바꾸고, 결정론적 코드가 그 SQL을 검증·교정·실행한다.
SQL을 아는 사람에게는 스키마 탐색, 실행계획·튜닝, 스키마 설계 진단(Design Lab) 같은
"DBMS를 이해하는 도구"를 함께 제공한다.

- PostgreSQL 전용 (ANTLR4 PostgreSQL 문법으로 SQL을 파싱)
- LLM 공급자: Anthropic, OpenAI 호환(vLLM·Ollama 등 자체 서빙 포함), IBM watsonx
- 웹 관리 화면: 질의, 스키마 탐색(ERD), 규칙·용어집 관리, JOIN 그래프, BIRD 평가, 감사 로그

설계 상세는 `docs/pgxnl-design.md`, 결정 배경은 `docs/adr/`, 평가 기록은 `docs/eval-history.md`.

---

## 동작 방식

```
질문 ─▶ (질문 보강) ─▶ 스키마 링킹 ─▶ ReAct SQL 생성 ─▶ 후처리 규칙 ─▶ 검증 ─▶ 실행 ─▶ 답변 요약
          선택          임베딩 후보        LLM + 도구          결정론적       비용·권한
                        → LLM 테이블 선택  + 루프 안 가드
```

| 단계 | 하는 일 |
|---|---|
| 스키마 링킹 | 테이블별 M-Schema 표현을 임베딩해 후보를 고르고(재현율 위주), LLM이 필요한 테이블·조인만 다시 고른다(테이블 3개 이하 스키마는 전부 사용). |
| 스키마 컨텍스트 | M-Schema 형식(`【Foreign keys】 a.x=b.y`) + 승인된 조인 경로(`【Join paths】`) + 테이블별 용어집 |
| SQL 생성 | ReAct 루프(describe_table·sample_data·collect_stats·generate_sql 도구). 실행 오류가 날 모양은 루프 안 가드가 되돌려 모델이 고치게 한다. |
| 지식 계층 | **용어집**(질문 표현 → 컬럼, 모르는 값, 컬럼 구분) / **생성 규칙**(프롬프트) / **후처리 규칙**(SQL을 결정론적으로 고침) / **조언형 가드**(SQL 모양을 판정해 모델에게 알림) — 스키마별·대상별·전역 범위 |
| 검증 | 읽기 전용, 예상 비용 상한, 감사 로그 |

설계 원칙: ① 보조 컴포넌트를 모두 꺼도 필수 경로(질문→SQL→검증→실행→답변)는 성립한다.
② LLM은 자연어를 다루는 지점에만 쓰고, 구조화된 판단은 코드가 한다. ③ 캐시 히트도 검증을 다시 통과한다.

---

## 요구 사항

- Python 3.12+
- PostgreSQL 14+ (시스템 DB용. 질의 대상 DB는 별도여도 됨) + `pgvector` 확장
- LLM 1개(채팅) + 임베딩 모델 1개 — 자체 서빙(vLLM 등의 OpenAI 호환 API)도 가능

## 검증된 모델 구성

이 저장소의 규칙·용어집·평가 결과는 **대부분 아래 구성 하나에서 만들고 측정했다.**
다른 모델에서는 같은 규칙의 효과가 달라질 수 있다(특히 few-shot·생성 규칙은 모델 의존적).

| 구분 | 구성 |
|---|---|
| LLM | `Qwen/Qwen3.8-27B-FP8` (dense), vLLM, **NVIDIA L40S 48GB 1장** |
| 임베딩 | `granite-embedding-278m` (768차원), vLLM CPU 이미지 |
| thinking | 모든 단계에서 끔(단계 설정 `disable_thinking=true`) |
| 속도 | 출력 약 19 tok/s → 한 호출 출력 약 3천 토큰 이하(호출 상한 180초) |

모델 선택 근거 (2026-09, california_schools 30문항, 튜닝 전 같은 설정에서 3회 평균):

| 모델 | EX |
|---|---|
| Qwen3.8-27B-FP8 (dense) | 65.6% |
| gpt-oss-120b (watsonx) | 53.3% |
| Qwen3.6-35B-A3B-FP8 (MoE) | 38.9% |

vLLM 기동 시 주의:
- `--tool-call-parser qwen3_coder` (hermes 로 두면 도구 호출 파싱이 조용히 실패해 ReAct가 멈춘다)
- `--reasoning-parser qwen3`, `--max-model-len 32768`
- `--default-chat-template-kwargs '{"enable_thinking": false}'` 는 **넣지 않는다** — thinking 은
  pgxnl 이 단계별로 제어한다.
- 자체 서명 인증서·thinking 설정은 `.env` 가 아니라 관리 화면의 **LLM 프로필 등록**에서 지정한다.

Anthropic·OpenAI·watsonx 공급자도 지원하지만, 위 구성만큼 반복 측정하지는 않았다.

## 설치

```bash
git clone <this repo> pgxnl && cd pgxnl
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

# 1) 시스템 DB(role·DB) 준비 — PostgreSQL 설치부터 하려면 스크립트 사용
scripts/install.sh            # 자세한 옵션: scripts/install.sh --help

# 2) 설정
cp .env.example .env          # LLM·임베딩·시스템 DB DSN·SECRET_KEY·관리자 비밀번호를 채운다

# 3) 실행 — 테이블 스키마(db/schema.sql)는 기동 시 자동 적용된다(idempotent)
uvicorn pgxnl.main:app --host 0.0.0.0 --port 8100
```

브라우저에서 `http://<host>:8100` → `admin` / `.env`의 `PGXNL_ADMIN_INITIAL_PASSWORD`로 로그인.

> **반드시 바꿀 것:** `PGXNL_SECRET_KEY`(32바이트 임의 값 — 저장되는 DB 비밀번호·API 키 암호화에 쓰임)와
> `PGXNL_ADMIN_INITIAL_PASSWORD`(기본 `passw0rd`). `.env`는 절대 커밋하지 않는다.

이후 관리 화면에서: **대상 DB 등록** → **모델 등록·단계 지정**(react·summarize 등 단계별 LLM) →
**스키마 벡터 색인** → 질의.

---

## 기준 정보(규칙·용어집·JOIN 그래프·gold 결함) 가져오기

BIRD 평가를 하며 다듬은 기준 정보를 `seed/`에 JSON으로 둔다. 새 환경에 넣으려면:

```bash
python tools/seed_import.py            # seed/*.json → 시스템 DB (기존 항목은 건너뜀, --replace 로 교체)
python tools/seed_export.py            # 현재 시스템 DB → seed/*.json (갱신할 때)
```

대상은 전역 항목과 `BIRD` 대상 항목이다(`--target` 으로 바꿀 수 있음). 규칙은 번호(id)를 유지해
문서의 "규칙 44" 같은 표기가 그대로 맞는다. LLM 프로필(API 키 포함)과 단계 설정은 내보내지 않는다 —
가져온 뒤 관리 화면에서 모델을 등록하고 단계마다 지정한다.

---

## BIRD 평가

[BIRD](https://bird-bench.github.io/) mini-dev(PostgreSQL 판) 500문항으로 정확도를 잰다.
데이터와 라이선스(CC BY-SA 4.0)는 `data/README.md`, 정정 내역은 `data/CHANGES.md`.

1. **대상 DB:** PostgreSQL DB 하나(예: `BIRD`, 약 1GB)에 BIRD 데이터베이스 11개를 **db_id 이름의 스키마**로
   적재한다(`card_games`, `california_schools`, … — 평가는 db_id 를 스키마 이름으로 쓴다).
   덤프는 저장소에 없다(약 1GB, BIRD 배포물). [bird-bench/mini_dev](https://github.com/bird-bench/mini_dev)
   README 의 "BIRD Mini-Dev Complete Package" 를 받아 압축을 풀면 `MINIDEV_postgresql/BIRD_dev.sql` 이 있다.
   공식 안내(`psql -d BIRD -f BIRD_dev.sql`)대로 넣으면 테이블이 모두 `public` 에 들어가므로, 대신 아래
   스크립트로 적재한다 — 적재 뒤 db_id 스키마로 옮기고 california_schools 의 `frpm`·`schools` 고유 인덱스를
   PK 로 올린다.
   ```bash
   PGHOST=... PGUSER=... PGPASSWORD=... scripts/load_bird_db.sh --dump BIRD_dev.sql --db BIRD
   ```
   `pg_stat_statements` 확장을 켜 두면 JOIN 이력 발견이 동작한다(슈퍼유저 필요).
2. 관리 화면에서 대상 이름 `BIRD`로 등록 → 스키마 벡터 전체 색인.
3. 기준 정보 가져오기(위 절).
4. 관리 화면 → BIRD 평가 → 스키마 선택 → 실행. 채점은 두 가지:
   - **pgxnl EX:** 행 순서 무시, 중복은 셈, 숫자는 소수 5자리 반올림
   - **공식 EX:** BIRD 공식 스크립트와 같게 결과 집합 비교(값 그대로)

### 현재 결과 (정정 데이터셋, Qwen3.8-27B-FP8 · L40S 1장, 2026-10)

| 스키마 | 문항 | pgxnl EX | 공식 EX | 비고 |
|---|---|---|---|---|
| codebase_community | 49 | 43 | 43 | 스키마 전용 용어집·규칙·가드 |
| card_games | 52 | 45 | 47 | 〃 |
| california_schools | 30 | 30 | 30 | 〃 |
| debit_card_specializing | 30 | 26 | 25 | 〃 + JOIN 경로 등록(FK 없음) |
| superhero | 52 | 42 | 42 | 전용 설정 없음(첫 측정) |
| student_club | 48 | 35 | 37 | 〃 |
| european_football_2 | 51 | 29 | 30 | 〃 |
| formula_1 | 66 | 32 | 34 | 〃 |
| thrombosis_prediction | 50 | 22 | 26 | 〃 |
| toxicology | 40 | 14 | 18 | 〃 |
| financial | 32 | 12 | 13 | 〃 |
| **합계** | **500** | **330** | **345** | |

위 4개 스키마는 정정 데이터셋 기준이라 원본 BIRD 점수와 직접 비교할 수 없다.
BIRD로 프롬프트를 과도하게 튜닝하지 않는다는 원칙과 그 근거는 `docs/eval-history.md`에 있다.

---

## 디렉터리

```
pgxnl/
  agent/          Orchestrator, ReAct planner, 도구, 후처리 규칙(canonicalize), 가드, 테이블 선택, 평가
  cache/          스키마 캐시, 스키마 벡터 인덱스, 시맨틱 캐시
  connectors/     대상 DB 연결
  governance/     생성·후처리 규칙, 용어집 저장소
  llm/            LLM·임베딩 클라이언트
  parsing/        ANTLR4 PostgreSQL 파서 래퍼, IR
  grammar/        생성된 파서 코드 (antlr/grammars-v4, MIT)
  api/            FastAPI 라우터 + 관리 화면(static)
db/schema.sql     시스템 DB 스키마 (기동 시 자동 적용)
seed/             기준 정보 JSON (규칙·용어집·JOIN 그래프·gold 결함)
data/             BIRD 데이터셋 (CC BY-SA 4.0)
scripts/          설치 스크립트
tools/            기준 정보 가져오기·내보내기, 분석 도구
docs/             설계, ADR, 평가 기록
tests/            단위 테스트 (pytest)
```

## 테스트

```bash
pytest -q
```

## 라이선스

- 소스 코드: [MIT](LICENSE)
- `data/`의 BIRD 유래 파일: [CC BY-SA 4.0](data/README.md)
- 서드파티 구성요소: [NOTICE](NOTICE)
