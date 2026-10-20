#!/usr/bin/env bash
# pgxnl 초기 설치: (선택) PostgreSQL+pgvector 설치 → 시스템 DB role·DB 생성 → Python venv → .env
#
# 테이블은 만들지 않는다 — 서버가 기동할 때 db/schema.sql 을 자동 적용한다(idempotent).
# 확장(vector, pg_trgm)은 슈퍼유저 권한이 필요해 여기서 미리 만든다.
set -euo pipefail

usage() {
  cat <<'EOF'
사용법: scripts/install.sh [옵션]

  --install-pg        PostgreSQL 16 + pgvector 를 OS 패키지로 설치 (Debian/Ubuntu: apt, RHEL 계열: dnf+PGDG)
  --container         PostgreSQL 대신 컨테이너(pgvector/pgvector:pg16)를 podman/docker 로 띄움
  --db-name NAME      시스템 DB 이름        (기본 pgxnl)
  --db-user USER      시스템 DB 소유 role   (기본 pgxnl)
  --db-password PW    role 비밀번호         (기본: 임의 생성)
  --db-host HOST      (기본 localhost)
  --db-port PORT      (기본 5432)
  --skip-db           role·DB 생성 건너뜀(이미 있을 때)
  --skip-venv         Python 가상환경·패키지 설치 건너뜀
  --force-env         .env 가 있어도 새로 만듦 (기존 파일은 .env.bak.<시각> 으로 보관)
  -h, --help

예)
  scripts/install.sh --install-pg          # 새 서버: PG 설치부터
  scripts/install.sh                       # PG 는 이미 있음(로컬 postgres 슈퍼유저 사용)
  scripts/install.sh --container           # PG 를 컨테이너로
EOF
}

DB_NAME=pgxnl DB_USER=pgxnl DB_PASSWORD="" DB_HOST=localhost DB_PORT=5432
INSTALL_PG=0 CONTAINER=0 SKIP_DB=0 SKIP_VENV=0 FORCE_ENV=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-pg) INSTALL_PG=1 ;;
    --container) CONTAINER=1 ;;
    --db-name) DB_NAME=$2; shift ;;
    --db-user) DB_USER=$2; shift ;;
    --db-password) DB_PASSWORD=$2; shift ;;
    --db-host) DB_HOST=$2; shift ;;
    --db-port) DB_PORT=$2; shift ;;
    --skip-db) SKIP_DB=1 ;;
    --skip-venv) SKIP_VENV=1 ;;
    --force-env) FORCE_ENV=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
log() { printf '\n==> %s\n' "$*"; }
rand() { python3 -c "import secrets; print(secrets.token_hex($1))"; }
[[ -n "$DB_PASSWORD" ]] || DB_PASSWORD=$(rand 16)

# ── 1. PostgreSQL ───────────────────────────────────────────
if [[ $INSTALL_PG -eq 1 && $CONTAINER -eq 1 ]]; then
  echo "--install-pg 와 --container 는 함께 쓸 수 없다" >&2; exit 1
fi

if [[ $INSTALL_PG -eq 1 ]]; then
  . /etc/os-release
  if command -v apt-get >/dev/null; then
    log "PostgreSQL + pgvector 설치 (apt)"
    sudo apt-get update
    sudo apt-get install -y postgresql postgresql-contrib
    PGV=$(psql --version | sed -E 's/.* ([0-9]+)\..*/\1/')
    sudo apt-get install -y "postgresql-${PGV}-pgvector"
  elif command -v dnf >/dev/null; then
    log "PostgreSQL 16 + pgvector 설치 (dnf, PGDG 저장소)"
    MAJ=${VERSION_ID%%.*}
    sudo dnf install -y "https://download.postgresql.org/pub/repos/yum/reporpms/EL-${MAJ}-$(uname -m)/pgdg-redhat-repo-latest.noarch.rpm"
    sudo dnf -qy module disable postgresql || true
    sudo dnf install -y postgresql16-server postgresql16-contrib pgvector_16
    sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
    sudo systemctl enable --now postgresql-16
    echo "참고: 다른 호스트에서 접속하려면 pg_hba.conf·listen_addresses 를 직접 설정한다."
  else
    echo "지원하지 않는 패키지 관리자 — PostgreSQL 14+ 와 pgvector 를 직접 설치한 뒤 --install-pg 없이 다시 실행" >&2
    exit 1
  fi
fi

if [[ $CONTAINER -eq 1 ]]; then
  RT=$(command -v podman || command -v docker || true)
  [[ -n "$RT" ]] || { echo "podman/docker 가 없다" >&2; exit 1; }
  log "컨테이너로 PostgreSQL 기동 ($RT, pgvector/pgvector:pg16, 포트 $DB_PORT)"
  # 컨테이너 안에서는 POSTGRES_USER 가 슈퍼유저 겸 소유자다 — 확장도 그 role 로 만든다
  "$RT" run -d --name pgxnl-pg -p "${DB_PORT}:5432" \
    -e POSTGRES_USER="$DB_USER" -e POSTGRES_PASSWORD="$DB_PASSWORD" -e POSTGRES_DB="$DB_NAME" \
    -v pgxnl-pgdata:/var/lib/postgresql/data docker.io/pgvector/pgvector:pg16
  for _ in $(seq 1 30); do
    "$RT" exec pgxnl-pg pg_isready -U "$DB_USER" >/dev/null 2>&1 && break; sleep 1
  done
  "$RT" exec pgxnl-pg psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
  SKIP_DB=1
fi

# ── 2. role·DB ──────────────────────────────────────────────
if [[ $SKIP_DB -eq 0 ]]; then
  log "시스템 DB 생성: role=$DB_USER db=$DB_NAME (로컬 postgres 슈퍼유저로)"
  PSQL=(sudo -u postgres psql -v ON_ERROR_STOP=1 -X -q)
  [[ -x /usr/pgsql-16/bin/psql ]] && PSQL=(sudo -u postgres /usr/pgsql-16/bin/psql -v ON_ERROR_STOP=1 -X -q)
  "${PSQL[@]}" -v u="$DB_USER" -v p="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'u', :'p')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'u') \gexec
SELECT format('ALTER ROLE %I PASSWORD %L', :'u', :'p') \gexec
SQL
  "${PSQL[@]}" -v u="$DB_USER" -v d="$DB_NAME" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'d', :'u')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'d') \gexec
SQL
  "${PSQL[@]}" -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
fi

# ── 3. Python ───────────────────────────────────────────────
if [[ $SKIP_VENV -eq 0 ]]; then
  PY=$(command -v python3.12 || command -v python3)
  "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || { echo "Python 3.12 이상이 필요하다 ($PY: $("$PY" --version))" >&2; exit 1; }
  log "Python 가상환경(.venv) + 패키지 설치"
  [[ -d .venv ]] || "$PY" -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -e ".[dev]"
fi

# ── 4. .env ─────────────────────────────────────────────────
if [[ -f .env && $FORCE_ENV -eq 0 ]]; then
  log ".env 가 이미 있어 그대로 둔다 (새로 만들려면 --force-env)"
  echo "시스템 DB DSN: postgresql://${DB_USER}:<비밀번호>@${DB_HOST}:${DB_PORT}/${DB_NAME}"
else
  [[ -f .env ]] && cp .env ".env.bak.$(date +%Y%m%d%H%M%S)"
  ADMIN_PW=$(rand 8)
  log ".env 생성"
  sed -e "s|^PGXNL_SYSTEM_PG_DSN=.*|PGXNL_SYSTEM_PG_DSN=postgresql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}|" \
      -e "s|^PGXNL_SECRET_KEY=.*|PGXNL_SECRET_KEY=$(rand 32)|" \
      -e "s|^PGXNL_ADMIN_INITIAL_PASSWORD=.*|PGXNL_ADMIN_INITIAL_PASSWORD=${ADMIN_PW}|" \
      .env.example > .env
  chmod 600 .env
  echo "관리자 로그인: admin / ${ADMIN_PW}   (.env 에 기록됨 — 첫 로그인 후 바꿀 것)"
fi

cat <<EOF

설치 끝. 남은 일:
  1) .env 의 LLM·임베딩 항목을 채운다 (README '검증된 모델 구성' 참고)
  2) 서버 기동:  .venv/bin/uvicorn pgxnl.main:app --host 0.0.0.0 --port 8100
     (첫 기동 때 db/schema.sql 이 적용된다)
  3) 기준 정보:  .venv/bin/python tools/seed_import.py
  4) 관리 화면 http://localhost:8100 → 대상 DB 등록 → LLM 프로필·단계 지정 → 스키마 벡터 색인
EOF
