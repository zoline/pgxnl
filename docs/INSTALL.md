# pgxnl 설치·설정 매뉴얼

이 문서는 아래 **예시 구성** 하나를 처음부터 끝까지 따라 하는 순서로 쓴다.
주소·이름은 예시이므로 자기 환경에 맞게 바꾼다.

> **`192.168.0.100` 은 설명을 위해 정한 임의의 사설 IP 다.** 실제 LLM 서버 주소로 바꿔 읽는다.
> 이 문서에 나오는 비밀번호(`<비밀번호>`), role 이름(`pgxnl_reader`), 서비스 사용자(`pgxnl-app`),
> 경로(`/opt/pgxnl`, `/data/hf`)도 모두 예시다.

```
┌──────────────────────────── pgxnl 서버 (이 문서의 "로컬") ────────────────────────────┐
│  pgxnl (uvicorn, :8100)                                                              │
│  PostgreSQL 16 (:5432)                                                               │
│    ├─ DB pgxnl   ← 시스템 DB: 사용자·규칙·용어집·캐시·평가 기록 (role pgxnl)          │
│    └─ DB BIRD    ← 질의 대상 DB: BIRD 11개 스키마 (읽기 전용 role pgxnl_reader)       │
└───────────────────────────────────────┬──────────────────────────────────────────────┘
                                        │ HTTP
┌───────────────────── LLM 서버 192.168.0.100 (GPU: NVIDIA L40S 48GB × 1) ─────────────┐
│  vLLM :8000  qwen3.8-27b              ← 채팅 LLM (Qwen/Qwen3.8-27B-FP8)               │
│  vLLM :8001  granite-embedding-278m   ← 임베딩 (768차원, CPU)                         │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

| 항목 | 예시 값 |
|---|---|
| pgxnl 접속 | `http://localhost:8100` |
| 시스템 DB | `postgresql://pgxnl:<비밀번호>@localhost:5432/pgxnl` |
| 대상 DB | `postgresql://pgxnl_reader:<비밀번호>@localhost:5432/BIRD` |
| 채팅 LLM | `http://192.168.0.100:8000/v1`, 모델 이름 `qwen3.8-27b` |
| 임베딩 | `http://192.168.0.100:8001/v1`, 모델 이름 `granite-embedding-278m` |

목차
1. 준비물
2. LLM 서버 (vLLM)
3. PostgreSQL
4. pgxnl 설치
5. 첫 기동과 관리 화면 설정
6. BIRD 평가 재현
7. 운영
8. 문제 해결
9. 업그레이드

---

## 1. 준비물

| 구분 | 최소 | 이 저장소에서 검증한 구성 |
|---|---|---|
| pgxnl 서버 | Linux, Python 3.12+, RAM 4GB | Ubuntu 24.04 계열, Python 3.12 |
| PostgreSQL | 14+ + pgvector + pg_trgm | 16 |
| 채팅 LLM | 도구 호출(function calling)을 지원하는 모델 | Qwen3.8-27B-FP8, vLLM, L40S 48GB 1장 |
| 임베딩 | OpenAI 호환 `/v1/embeddings` | granite-embedding-278m (768차원) |

- 이 저장소의 규칙·용어집·평가 수치는 위 "검증한 구성"에서 만든 것이다. 다른 모델에서는 같은
  규칙의 효과가 다를 수 있다.
- 클라우드 LLM(Anthropic, OpenAI, IBM watsonx)도 쓸 수 있다 — 5.3 절에서 공급자만 바꾸면 된다.
  이 경우 2 절(vLLM)은 건너뛴다.
- 임베딩 차원은 **768 고정**이다(`db/schema.sql` 의 `vector(768)`). 다른 차원의 모델을 쓰려면 8 절을 본다.

---

## 2. LLM 서버 (vLLM) — 192.168.0.100

pgxnl 은 OpenAI 호환 API 로 붙는다. 여기서는 vLLM 을 예로 든다.

### 2.1 채팅 LLM (:8000)

검증한 구성(L40S 48GB 1장)에서 실제로 쓰는 옵션:

```bash
vllm serve \
  --model Qwen/Qwen3.8-27B-FP8 \
  --served-model-name qwen3.8-27b \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.95 \
  --max-model-len 131072 \
  --max-num-seqs 4 \
  --kv-cache-dtype fp8 \
  --enable-prefix-caching \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --generation-config vllm \
  --api-key <임의의 키>
```

| 옵션 | 뜻 |
|---|---|
| `--max-model-len 131072` | 최대 문맥. pgxnl 한 요청은 평균 입력 약 2.6천 토큰이라 여유가 크다 |
| `--max-num-seqs 4` | 동시 처리 요청 수. BIRD 평가 동시 처리 수(1~3)와 질의가 겹쳐도 대기열이 짧다 |
| `--kv-cache-dtype fp8` | KV 캐시를 FP8 로 — 48GB 한 장에 긴 문맥·동시 요청을 담기 위해 |
| `--enable-prefix-caching` | 같은 시스템 프롬프트·스키마 앞부분을 재사용. 실측 적중률 약 59% |
| `--generation-config vllm` | 모델 저장소의 기본 샘플링 값(generation_config.json) 대신 vLLM 기본값을 쓴다 — 온도 등은 pgxnl 이 요청마다 보낸다 |
| `--api-key` | 이 키를 아는 클라이언트만 받는다. **pgxnl 의 모델 등록(5.3 절) API Key 칸에 같은 값을 넣는다** |

반드시 지킬 것:

| 옵션 | 이유 |
|---|---|
| `--tool-call-parser qwen3_coder` | Qwen3 계열은 `<tool_call><function=…>` XML 형식으로 도구를 부른다. `hermes` 로 두면 파싱이 **조용히** 실패해 도구 호출이 비고, pgxnl 의 ReAct 루프가 SQL 을 못 만든다. |
| `--enable-auto-tool-choice` | 도구 호출 응답을 켠다. |
| `--reasoning-parser qwen3` | thinking 출력과 본문을 분리한다. |
| `--default-chat-template-kwargs '{"enable_thinking": false}'` 는 **넣지 않는다** | thinking 은 pgxnl 이 단계별로 끈다(5.3 절). 서버 기본값으로 끄면 단계 설정과 어긋난다. |

컨테이너(podman)로 띄울 때 RHEL 계열이면 모델 캐시 볼륨에 SELinux 레이블 `:z` 를 붙인다
(`-v /data/hf:/root/.cache/huggingface:z`). 없으면 root 로 띄워도 `Permission denied` 가 난다.

### 2.2 임베딩 (:8001)

GPU 가 1장이면 임베딩은 CPU 로 따로 띄운다(vLLM CPU 이미지 `vllm/vllm-openai-cpu` 등).

검증한 구성에서 실제로 쓰는 옵션:

```bash
vllm serve \
  --model ibm-granite/granite-embedding-278m-multilingual \
  --served-model-name granite-embedding-278m \
  --max-model-len 512 \
  --host 0.0.0.0 --port 8001
```

- `--max-model-len 512` — 이 모델(XLM-RoBERTa 계열)의 최대 입력 길이다.
- `--served-model-name` 은 pgxnl 의 임베딩 설정(5.4 절) Model 칸에 넣는 이름이 된다.
- 출력은 768차원이다(pgxnl 이 요구하는 차원).

### 2.3 확인

pgxnl 서버에서:

```bash
curl -s http://192.168.0.100:8000/v1/models -H 'Authorization: Bearer <임의의 키>' | python3 -m json.tool | grep '"id"'
curl -s http://192.168.0.100:8001/v1/embeddings -H 'Content-Type: application/json' \
  -d '{"model":"granite-embedding-278m","input":"hello"}' | python3 -c 'import sys,json; print(len(json.load(sys.stdin)["data"][0]["embedding"]))'
# → 768
```

방화벽에서 8000·8001 포트를 pgxnl 서버에 열어 둔다.

---

## 3. PostgreSQL — 로컬

### 3.0 이미 PostgreSQL 이 설치되어 있으면

새로 설치하지 않는다. `install.sh` 를 **`--install-pg` 없이** 실행하면 기존 PostgreSQL 에
role·DB 만 만든다. 먼저 세 가지를 확인한다.

```bash
psql --version                                             # 14 이상이어야 한다
ls "$(pg_config --sharedir)/extension/vector.control"      # pgvector 가 설치돼 있는지
sudo -u postgres psql -c "select version()"                # 슈퍼유저로 접속되는지
```

| 상황 | 할 일 |
|---|---|
| 같은 서버, PG 14+ 있음, pgvector 없음 | 그 **주 버전에 맞는** pgvector 패키지만 설치: Ubuntu `postgresql-<버전>-pgvector`, RHEL(PGDG) `pgvector_<버전>`. 그다음 `scripts/install.sh` |
| 같은 서버, 다 있음 | `scripts/install.sh` (5432 가 아니면 `--db-port`) |
| 여러 버전이 함께 있음 | 쓸 클러스터의 포트를 `--db-port` 로. Ubuntu 는 `pg_lsclusters` 로 확인 |
| DB 가 다른 서버·관리형(RDS 등)이거나 `sudo -u postgres` 가 안 됨 | 아래 SQL 을 슈퍼유저(관리형은 관리자 role)로 직접 실행하고 `scripts/install.sh --skip-db --db-host <주소> --db-password <비밀번호>` |
| `--container` 로 따로 띄우고 싶은데 5432 를 기존 PG 가 씀 | `scripts/install.sh --container --db-port 5433` |

직접 만들 때의 SQL (install.sh 가 하는 것과 같다):
```sql
CREATE ROLE pgxnl LOGIN PASSWORD '<비밀번호>';
CREATE DATABASE pgxnl OWNER pgxnl;
\c pgxnl
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

주의:
- **`pgxnl` role 이 이미 있으면 install.sh 가 그 비밀번호를 새 값으로 바꾼다.** 다른 용도로 쓰는 같은
  이름의 role 이 있으면 `--db-user` 로 다른 이름을 쓰거나, 기존 비밀번호를 `--db-password` 로 넘긴다.
- 같은 이름의 DB 가 이미 있으면 만들지 않고 그대로 쓴다. pgxnl 테이블은 모두 `pgxnl_` 로 시작하므로
  다른 테이블과 섞여도 동작은 하지만, 전용 DB 를 권한다.
- 기존 PG 설정(`postgresql.conf`, `pg_hba.conf`)은 건드리지 않는다. pg_stat_statements 가 필요하면 3.2 절.
- 기존 운영 DB 를 **질의 대상**으로 쓰는 것은 별개다 — 5.5 절처럼 읽기 전용 role 을 만들어 등록한다.

### 3.1 새로 설치

`scripts/install.sh --install-pg` 가 아래를 대신한다(4 절). 직접 하려면:

**Ubuntu / Debian**
```bash
sudo apt-get install -y postgresql postgresql-contrib postgresql-16-pgvector
```

**RHEL 9 계열** (PGDG 저장소)
```bash
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf -qy module disable postgresql
sudo dnf install -y postgresql16-server postgresql16-contrib pgvector_16
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16
```

**컨테이너** — `scripts/install.sh --container` (이미지 `pgvector/pgvector:pg16`).

### 3.2 pg_stat_statements (선택, 권장)

pgxnl 의 **SQL 수집**·**JOIN 그래프 발견**은 대상 DB 의 `pg_stat_statements` 를 읽는다.
없어도 질의는 되지만 이 두 기능이 비게 된다.

```bash
# postgresql.conf (Ubuntu: /etc/postgresql/16/main/postgresql.conf)
shared_preload_libraries = 'pg_stat_statements'
```
```bash
sudo systemctl restart postgresql          # RHEL: postgresql-16
```
확장 생성은 대상 DB 를 만든 뒤 6.1 절에서 한다(`load_bird_db.sh` 가 시도한다).

### 3.3 원격 접속 (pgxnl 과 DB 가 다른 서버일 때만)

이 예시는 같은 서버라 필요 없다. 나눌 경우 `postgresql.conf` 의 `listen_addresses` 와
`pg_hba.conf` 에 pgxnl 서버 주소를 추가한다.

---

## 4. pgxnl 설치

```bash
git clone https://github.com/zoline/pgxnl.git
cd pgxnl
scripts/install.sh --install-pg        # PG 가 이미 있으면 --install-pg 빼고
```

`install.sh` 가 하는 일:

1. (옵션) PostgreSQL 16 + pgvector 설치
2. 시스템 DB role `pgxnl` 과 DB `pgxnl` 생성(소유자 pgxnl), 확장 `vector`·`pg_trgm` 생성
   — 확장은 슈퍼유저가 필요해서 여기서 미리 만든다(`sudo -u postgres` 사용)
3. `.venv` 가상환경 + `pip install -e ".[dev]"`
4. `.env` 생성 — 시스템 DB DSN, 임의 `PGXNL_SECRET_KEY`, 임의 관리자 비밀번호

| 옵션 | 뜻 |
|---|---|
| `--install-pg` | PostgreSQL+pgvector 를 OS 패키지로 설치 |
| `--container` | PostgreSQL 을 컨테이너로 |
| `--db-name` / `--db-user` / `--db-password` | 시스템 DB 이름·role·비밀번호 (기본 pgxnl / pgxnl / 임의) |
| `--db-host` / `--db-port` | 기본 localhost / 5432 |
| `--skip-db` / `--skip-venv` | 해당 단계 건너뜀 |
| `--force-env` | `.env` 가 있어도 새로 만듦(기존 것은 `.env.bak.<시각>`) |

끝에 관리자 비밀번호가 **한 번** 출력된다. 같은 값이 `.env` 의
`PGXNL_ADMIN_INITIAL_PASSWORD` 에 남는다(README "처음 설치할 때 비밀번호는 어디에 기록되나").

### 4.1 `.env` 채우기

`install.sh` 가 DB·비밀 값은 채워 두므로, LLM 기본값과 링킹 값만 확인한다. 예시 구성 기준:
**임베딩 모델은 `.env` 에 없다** — 첫 로그인 뒤 관리 화면에서 정한다(5.4 절).

```bash
# ── LLM (.env 값은 기본·대체용. 실제 단계별 모델은 관리 화면 5.3 절에서 정한다) ──
PGXNL_LLM_PROVIDER=openai
PGXNL_LLM_MODEL=qwen3.8-27b
PGXNL_LLM_BASE_URL=http://192.168.0.100:8000/v1
PGXNL_LLM_MAX_TOKENS=4096
OPENAI_API_KEY=dummy                          # openai 공급자는 이 키를 읽는다. vLLM 이면 아무 값

# ── 스키마 링킹 (BIRD 평가 기준 값) ──
PGXNL_SCHEMA_VECTOR_ENABLED=true
PGXNL_SCHEMA_VECTOR_SCORE_MARGIN=0.10
PGXNL_SCHEMA_VECTOR_KEEP_ALL_MAX_TABLES=3
PGXNL_TABLE_SELECT_ENABLED=true
PGXNL_TABLE_SELECT_CANDIDATE_MARGIN=0.15
```

주요 항목:

| 항목 | 설명 |
|---|---|
| `PGXNL_SYSTEM_PG_DSN` | 시스템 DB. install.sh 가 채움 |
| `PGXNL_SECRET_KEY` | 저장되는 대상 DB 비밀번호·API 키를 암호화하는 키. **설치 뒤 바꾸면 저장된 값을 못 푼다** |
| `PGXNL_ADMIN_INITIAL_PASSWORD` | 관리자 `pgxnl` 계정의 첫 비밀번호. 첫 기동 때만 쓰임 |
| `PGXNL_SCHEMA_VECTOR_SCORE_MARGIN` | 1위 테이블 점수 대비 이 차이 이내만 후보로. 임베딩 모델을 바꾸면 재조정 |
| `PGXNL_TABLE_SELECT_ENABLED` | 임베딩 후보에서 LLM 이 테이블을 다시 고름. 질문당 LLM 호출 1회 추가 |
| `PGXNL_ENRICHMENT_ENABLED` | 질문 보강(모호성 판단·재작성). 기본 꺼짐 |
| `PGXNL_VALIDATION_MAX_COST` | EXPLAIN 예상 비용이 이보다 크면 실행 거부 |
| `PGXNL_AGENT_MAX_ITERATIONS` | ReAct 루프 최대 반복 |
| `PGXNL_API_PORT` | 기본 8100 |

### 4.2 서비스로 등록 (선택)

`/etc/systemd/system/pgxnl.service`
```ini
[Unit]
Description=pgxnl
After=network-online.target postgresql.service

[Service]
User=pgxnl-app
WorkingDirectory=/opt/pgxnl
ExecStart=/opt/pgxnl/.venv/bin/uvicorn pgxnl.main:app --host 0.0.0.0 --port 8100
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now pgxnl
journalctl -u pgxnl -f
```

`--reload` 없이 띄우므로 **코드나 `.env` 를 고치면 재기동해야 반영된다.**

---

## 5. 첫 기동과 관리 화면 설정

### 5.1 기동

백그라운드로 띄우고 로그는 파일로 남긴다(터미널을 닫아도 계속 돈다):

```bash
nohup .venv/bin/uvicorn pgxnl.main:app --host 0.0.0.0 --port 8100 > pgxnl.log 2>&1 &
tail -f pgxnl.log            # 기동 로그 확인 (Ctrl+C 로 tail 만 빠져나온다)
```

멈추거나 다시 띄울 때:
```bash
pkill -f "uvicorn pgxnl.main:app"     # 중지
# 다시 띄우려면 위 nohup 명령을 다시 실행
```

계속 운영할 서버라면 4.2 절의 systemd 서비스로 등록하는 편이 낫다.

첫 기동 때:
- `db/schema.sql` 이 시스템 DB 에 적용된다(여러 번 실행해도 안전).
- 관리자 계정 `pgxnl` 이 만들어지고, 로그(`pgxnl.log`)에 API 키가 **한 번** 찍힌다:
  `admin 계정이 생성되었습니다. username=pgxnl api_key=…` — API 로 호출할 일이 있으면 적어 둔다.

확인:
```bash
curl -s http://localhost:8100/healthz
```

### 5.2 로그인과 비밀번호 변경

브라우저 `http://localhost:8100` → `pgxnl` / `.env` 의 `PGXNL_ADMIN_INITIAL_PASSWORD`.
**내 설정 → 비밀번호** 에서 바꾼다.

### 5.3 모델 등록과 단계별 지정 — 관리 → 모델 설정

**① 모델 추가** 탭

| 칸 | 예시 값 |
|---|---|
| 표시 이름 | `qwen-27b` |
| Provider | OpenAI 호환 (vLLM/Ollama) |
| Model | `qwen3.8-27b` (vLLM `--served-model-name` 과 같게) |
| Base URL | `http://192.168.0.100:8000/v1` |
| Temperature | `0` |
| Max Tokens | `4096` |
| SSL 검증 | HTTPS + 자체 서명 인증서면 "검증 안 함" |
| API Key | vLLM `--api-key` 로 준 값 (안 줬으면 아무 값) |

자체 서명 인증서와 thinking 설정은 `.env` 가 아니라 이 화면을 거쳐야만 전달된다.

**② 단계별 지정** 탭 — 모든 단계에 위 모델을 지정한다. **Thinking 은 기본이 끔**이므로 그대로 둔다.

| 단계 | 하는 일 |
|---|---|
| react | 스키마 탐색·SQL 생성(실제로 SQL 을 쓰는 단계). LLM 테이블 선택도 이 모델을 쓴다 |
| generate_sql | 폴백 — ReAct 가 SQL 없이 도구를 불렀을 때 |
| summarize | 실행 결과를 자연어 답으로 |
| enrich_detect / enrich_rewrite | 질문 보강(켰을 때만) |
| sql_tuning | 실행계획 분석·SQL 튜닝 화면 |
| column_rationale | 디버그 전용 — SELECT 항목 근거 |
| canonical_rewrite | 예시 쌍 기반 SQL 형태 교정 규칙 |
| describe_sql | 수집한 SQL 을 질문으로 바꿀 때 |

Qwen3 계열에서 thinking 을 켜면 단순한 판단도 수십 초가 걸리고, BIRD 정확도도 오히려 낮았다(실측).

### 5.4 임베딩 모델 — 관리 → 모델 설정 → 임베딩 (**대상 DB 등록 전에**)

질문에서 관련 테이블을 찾는 임베딩 모델이다. 서버 전체가 하나를 쓰고, 설정은 시스템 DB 에 저장된다
(API 키는 `PGXNL_SECRET_KEY` 로 암호화). **대상 DB 를 등록하기 전에 설정해야** 등록할 때 스키마 벡터가
만들어진다. 설정하지 않은 채 대상 DB 화면을 열면 경고가 나오고, 등록하려 하면 한 번 더 묻는다.

| 칸 | 예시 값 |
|---|---|
| Provider | OpenAI 호환 (vLLM/Ollama/OpenAI) |
| Model | `granite-embedding-278m` (vLLM `--served-model-name` 과 같게) |
| Base URL | `http://192.168.0.100:8001/v1` |
| API Key | 비워 둠 — vLLM 처럼 키를 안 보는 서버. OpenAI 는 키 입력 |
| SSL 검증 | HTTPS + 자체 서명 인증서면 "검증 안 함" |

**연결 테스트** → `연결 성공 — 768차원` 을 확인하고 **저장**. 저장할 때도 한 번 임베딩해 보고, 실패하거나
768차원이 아니면 저장하지 않는다.

| 공급자 | 설정 |
|---|---|
| vLLM·Ollama (OpenAI 호환) | Base URL·Model. 키는 비워도 됨 |
| OpenAI | Base URL `https://api.openai.com/v1`, Model `text-embedding-3-small`, 키 — OpenAI 에만 `dimensions=768` 을 보내 768 로 받는다 |
| IBM watsonx | 연결·자격은 **모델 추가** 에 등록한 watsonx 모델에서 빌려 온다. 그 모델을 고르고 Model 에 임베딩 모델 id 를 넣는다 |

지켜야 할 것:
- **차원은 768.** 시스템 DB 의 `vector(768)` 열에 들어간다. vLLM 등에는 차원 지정을 보내지 않으므로 모델
  자체가 768 을 내야 한다(granite-embedding-278m, nomic-embed-text 등).
- **모델을 바꾸면** 저장 뒤 "등록된 대상 DB 의 벡터를 다시 만들까요?" 를 묻는다 — 예를 누르면 모든 대상의
  스키마 벡터·사용례 임베딩을 새 모델로 다시 만들고 시맨틱 캐시의 임베딩은 지운다(백그라운드).
  옛 모델 벡터와 새 모델 질문 벡터는 비교할 수 없으므로 반드시 다시 만든다.
- 링킹 마진 `PGXNL_SCHEMA_VECTOR_SCORE_MARGIN`(0.10)·`PGXNL_TABLE_SELECT_CANDIDATE_MARGIN`(0.15) 은
  granite-embedding-278m 기준 값이다 — 다른 모델이면 재조정이 필요할 수 있다.

### 5.5 대상 DB 등록 — 관리 → 대상 DB

대상 DB 에는 **읽기 전용 role** 을 쓴다. pgxnl 은 읽기 전용 트랜잭션으로만 실행하지만,
권한에서도 막아 두는 것이 안전하다. BIRD 예시(6.1 절에서 DB 를 만든 뒤):

```sql
-- sudo -u postgres psql -d BIRD
CREATE ROLE pgxnl_reader LOGIN PASSWORD '<비밀번호>';
GRANT CONNECT ON DATABASE "BIRD" TO pgxnl_reader;
DO $$ DECLARE s text; BEGIN
  FOR s IN SELECT nspname FROM pg_namespace
           WHERE nspname NOT IN ('pg_catalog','information_schema','public') AND nspname NOT LIKE 'pg_%'
  LOOP
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO pgxnl_reader', s);
    EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO pgxnl_reader', s);
  END LOOP;
END $$;
GRANT pg_read_all_stats TO pgxnl_reader;   -- pg_stat_statements 를 읽으려면
```

화면에서:

| 칸 | 값 |
|---|---|
| 연결 이름 | **`BIRD`** (BIRD 기준 정보가 이 이름으로 묶여 있다 — 6 절) |
| 호스트 / 포트 / DB 이름 | `localhost` / `5432` / `BIRD` |
| 사용자 / 비밀번호 | `pgxnl_reader` / … |

**등록** 을 누르면 스키마 벡터 색인이 백그라운드에서 자동으로 시작된다(임베딩이 설정돼 있을 때).

### 5.6 스키마 벡터 확인 — 관리 → 캐시 → 벡터 인덱스

대상 DB 를 고르고 **조회** → 색인된 테이블 수가 실제 테이블 수와 같은지 본다(BIRD 75개).
로그에는 `[SchemaVector] BIRD 재구축 완료: 75 테이블` 이 찍힌다.

- **일부만 색인된 상태는 색인이 없는 것보다 나쁘다** — 색인된 테이블로만 링킹이 쏠린다.
  수가 모자라면 **초기화** 로 다시 만든다.
- 대상 DB 의 테이블을 바꿨을 때도 초기화한다.

### 5.7 첫 질의 — 분석 → Query

대상 DB 와 스키마를 고르고 질문한다. 예(BIRD, california_schools):

> What is the highest eligible free rate for K-12 students in the schools in Alameda County?

생성된 SQL·실행 결과·답변이 나오면 설치 끝.

---

## 6. BIRD 평가 재현

### 6.1 대상 DB 만들기

1. [bird-bench/mini_dev](https://github.com/bird-bench/mini_dev) README 의 "BIRD Mini-Dev Complete Package"
   를 받아 압축을 푼다 → `MINIDEV_postgresql/BIRD_dev.sql` (약 1GB).
2. 적재 (DB 생성 권한이 있는 role 로, pg_stat_statements 확장까지 만들려면 슈퍼유저로):
   ```bash
   sudo -u postgres scripts/load_bird_db.sh --dump /path/to/BIRD_dev.sql --db BIRD
   ```
   `postgres` 사용자가 덤프 파일과 저장소를 읽을 수 있어야 한다(홈 디렉터리 밑이면 권한을 주거나
   다른 위치로 옮긴다). 슈퍼유저 대신 DB 생성 권한이 있는 role 로 해도 되며, 그때는
   `PGHOST=localhost PGUSER=<role> PGPASSWORD=… scripts/load_bird_db.sh …` 로 실행한다.
   공식 덤프는 75개 테이블을 모두 `public` 에 넣는다. 스크립트는 적재 뒤 db_id 이름의 스키마
   11개(`card_games`, `california_schools`, …)로 옮기고, `frpm`·`schools` 의 고유 인덱스를 PK 로 올린다.
   pgxnl 평가는 db_id 를 스키마 이름으로 쓰므로 공식 안내(`psql -f`)대로 넣으면 평가가 안 된다.
3. 5.4 절의 임베딩이 설정돼 있는지 확인 → 5.5 절의 읽기 전용 role 을 만들고 대상 `BIRD` 로 등록 → 5.6 절로 색인 확인.

### 6.2 기준 정보 가져오기

```bash
.venv/bin/python tools/seed_import.py
```

| seed 파일 | 내용 |
|---|---|
| `seed/rules.json` | SQL 규칙(전역 + BIRD 스키마별). 번호 유지 |
| `seed/glossary.json` | 용어집 |
| `seed/join_graph.json` | JOIN 그래프(FK 없는 스키마의 조인 경로 승인 포함) |
| `seed/gold_defects.json` | gold 결함 판정과 근거 |

이미 있는 항목은 건너뛴다. 다시 덮으려면 `--replace`, 미리 보려면 `--dry-run`.
대상 이름이 `BIRD` 가 아니면 BIRD 전용 규칙·용어집이 적용되지 않는다.

### 6.3 평가 실행 — BIRD → BIRD 평가

| 칸 | 값 |
|---|---|
| 대상 DB | BIRD |
| 스키마 | 하나(예: `california_schools`, 30문항) 또는 전체(500문항) |
| 동시 처리 수 | 1 권장 |
| BIRD JSON 파일 | 비우면 `data/bird_minidev_pg.json`(정정본). 원본으로 재려면 `data/bird_minidev_pg.original.json` 업로드 |

- 평가는 시맨틱 캐시를 쓰지 않는다(설정 비교가 캐시에 오염되지 않게).
- **동시 처리 수 1 이면 같은 설정에서 문항 단위로 재현된다.** 3 이상이면 소수 문항이 흔들린다.
- 시간: 예시 구성에서 30문항 약 8분.
- 평가 중에 규칙·용어집·모델 설정을 바꾸지 않는다 — 문항마다 설정을 새로 읽어 중간 변경이 섞인다.

### 6.4 결과 읽기

| 지표 | 비교 방식 |
|---|---|
| pgxnl EX | 행 순서 무시, **중복 행은 셈**, 숫자는 소수 5자리 반올림 |
| 공식 EX | BIRD 공식 스크립트와 같이 결과 **집합** 비교, 값 그대로 |

- 항목 상세에서 문항별 생성 SQL·gold SQL·결과를 비교할 수 있다. 화면 번호는 데이터셋 안 순번(seq)이다.
- gold 결함으로 판정된 문항은 표시가 붙고, 근거는 `seed/gold_defects.json` 과 `data/CHANGES.md` 에 있다.
- README 의 결과표와 크게 다르면 8 절의 확인 순서를 따른다.

---

## 7. 운영

| 작업 | 위치 |
|---|---|
| 사용자 추가(user / admin) | 관리 → 사용자 |
| 사용자별 대상 DB 자격증명·단계 모델 | 내 설정 |
| 규칙·용어집 편집 | 기준정보 → SQL 규칙 / 용어집 |
| JOIN 후보 승인 | 분석 → JOIN 그래프 |
| 감사 로그 조회·정리 | 관리 → 감사 로그 (보관 기간 지정 삭제) |
| 상태 점검 | 관리 → 시스템 정보 (DB·pgvector·모델·단계 설정) |

기준 정보를 고친 뒤 다른 환경으로 옮기려면:
```bash
.venv/bin/python tools/seed_export.py      # 시스템 DB → seed/*.json
```

백업: 시스템 DB 는 `pg_dump -Fc pgxnl` 로 뜬다. jsonb 열(규칙 정의 등)을 `::text` 로 떠서
`::jsonb` 로 다시 넣는 식의 수작업 백업은 이중 인코딩으로 깨지므로 쓰지 않는다.

---

## 8. 문제 해결

| 증상 | 원인·조치 |
|---|---|
| 코드·`.env` 를 고쳤는데 그대로다 | 서버를 재기동하지 않았다(`--reload` 없이 띄움). |
| 질의가 SQL 없이 끝나거나 도구 호출이 비어 있다 | vLLM `--tool-call-parser` 가 `qwen3_coder` 가 아니다(2.1 절). |
| 단순한 단계도 수십 초 이상 걸린다 | 그 단계의 Thinking 이 켜져 있다(5.3 절). |
| `Request timed out` (약 3분) | 한 호출 출력이 너무 길다. 예시 구성은 출력 약 19 tok/s 라 호출 상한 180초 ≈ 3천 토큰. LLM 서버가 멈췄다고 재기동하기 전에 vLLM `/metrics` 의 `num_requests_running`·`generation_tokens_total` 이 늘고 있는지 본다. |
| 엉뚱한 테이블로 SQL 을 만든다 | 벡터 인덱스가 일부만 색인됐을 수 있다(5.6 절). 수를 확인하고 초기화. |
| 스키마 벡터가 0 개, "SchemaVectorIndex 비활성" | 임베딩 모델이 설정되지 않았다(5.4 절). 설정·저장한 뒤 재색인을 "예" 로 하거나, 캐시 → 벡터 인덱스에서 대상별 **초기화**. |
| 임베딩 저장 시 "이 모델은 N차원입니다" | 768차원 모델만 쓸 수 있다. 다른 차원이 꼭 필요하면 `db/schema.sql` 의 `vector(768)` 세 곳과 `pgxnl/llm/embedding_config.py` 의 `EMBEDDING_DIMENSIONS` 를 함께 바꾸고 벡터를 다시 만든다. |
| 임베딩 연결 테스트 실패 | 오류 문구를 본다 — 404 면 Model 이 vLLM `--served-model-name` 과 다르다, 연결 거부면 Base URL·방화벽, SSL 오류면 "SSL 검증 안 함". |
| 기동 로그에 확장 생성 권한 오류 | `vector`·`pg_trgm` 확장은 슈퍼유저가 만들어야 한다: `sudo -u postgres psql -d pgxnl -c "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;"` |
| SQL 수집·JOIN 발견이 비어 있다 | 대상 DB 에 `pg_stat_statements` 가 없거나(3.2 절), 대상 role 에 `pg_read_all_stats` 가 없다. |
| BIRD 평가 점수가 README 와 크게 다르다 | ① 대상 이름이 `BIRD` 인지 ② seed 를 가져왔는지 ③ 벡터 75개 색인 ④ 모델·단계별 Thinking 끔 ⑤ 동시 처리 수. 모델이 다르면 차이는 정상이다. |
| 평가 결과가 지난번과 다르다 | 동시 처리 수 3 이상이면 소수 문항이 흔들린다. 1 로 다시 잰다. 평가 중 설정을 바꾸지 않았는지도 본다. |
| 컨테이너 vLLM 이 모델 캐시에서 `Permission denied` | RHEL SELinux — 볼륨에 `:z` (2.1 절). |
| 대상 DB 비밀번호에 특수문자가 있어 등록이 안 된다 | "항목별 입력" 방식을 쓴다. DSN 직접 입력이면 특수문자를 %인코딩한다. |

로그: 직접 띄웠으면 터미널, systemd 면 `journalctl -u pgxnl`.

---

## 9. 업그레이드

```bash
git pull
.venv/bin/pip install -e ".[dev]"
sudo systemctl restart pgxnl                 # 또는 uvicorn 재기동 — schema.sql 이 자동 적용된다
.venv/bin/python tools/seed_import.py        # 새 기준 정보 추가(기존 항목은 유지)
```

0.5 초기 판에서 올라오면 `.env` 의 임베딩 설정(`PGXNL_EMBEDDING_*`, `EMBEDDING_API_KEY`)은 첫 기동 때
시스템 DB 로 한 번 옮겨지고(로그 "임베딩 설정을 .env 에서 시스템 DB 로 옮겼습니다"), 이후로는 읽지 않는다.
확인한 뒤 `.env` 에서 지워도 된다.

저장소의 기준 정보로 자기 환경의 같은 항목을 덮으려면 `--replace`. 직접 고친 항목이 있으면
먼저 `tools/seed_export.py` 로 떠 두고 비교한다.
