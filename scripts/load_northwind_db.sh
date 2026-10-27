#!/usr/bin/env bash
# Northwind(pthom/northwind_psql)를 pgxnl Northwind 평가용 대상 DB로 적재한다.
#
# 원본 데이터 기간은 1996-07 ~ 1998-05 다. 2026년 기준으로 쓰도록 날짜 열 5개(orders 3, employees 2)를
# +28년 옮긴다 — 그레고리력은 28년마다 요일·윤년이 같아 연·월·요일 집계가 바뀌지 않는다.
# 결과: 2024-07-04 ~ 2026-05-06. 평가 데이터셋(data/northwind_pg.json)은 이 기준으로 만들어져 있다.
#
# 접속 정보는 libpq 환경변수(PGHOST, PGPORT, PGUSER, PGPASSWORD). DB 생성 권한이 필요하다.
set -euo pipefail

URL="https://raw.githubusercontent.com/pthom/northwind_psql/master/northwind.sql"
DB=northwind DUMP=""
usage() {
  cat <<'EOF'
사용법: scripts/load_northwind_db.sh [--db northwind] [--dump northwind.sql]

  --db NAME     만들 DB 이름 (기본 northwind, 이미 있으면 중단)
  --dump PATH   이미 받아 둔 northwind.sql (없으면 GitHub 에서 받음)
EOF
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --db) DB=$2; shift ;;
    --dump) DUMP=$2; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

PSQL=(psql -X -q -v ON_ERROR_STOP=1)
TMP=""
if [[ -z "$DUMP" ]]; then
  TMP=$(mktemp -d); DUMP="$TMP/northwind.sql"
  echo "==> 내려받기: $URL"
  curl -fsSL -o "$DUMP" "$URL"
fi
# 덤프는 DDL·INSERT 만이어야 한다 — psql 메타 명령(\! 등)이 있으면 중단
if grep -qE '^\s*\\' "$DUMP"; then echo "덤프에 psql 메타 명령이 있다 — 중단" >&2; exit 1; fi

echo "==> DB 생성·적재: $DB"
createdb "$DB"
"${PSQL[@]}" -d "$DB" -f "$DUMP" >/dev/null

echo "==> 날짜 +28년"
"${PSQL[@]}" -d "$DB" <<'SQL'
BEGIN;
UPDATE orders SET order_date = order_date + interval '28 years',
                  required_date = required_date + interval '28 years',
                  shipped_date = shipped_date + interval '28 years';
UPDATE employees SET birth_date = birth_date + interval '28 years',
                     hire_date = hire_date + interval '28 years';
COMMIT;
ANALYZE;
SQL
if [[ -n "$TMP" ]]; then rm -rf "$TMP"; fi

"${PSQL[@]}" -d "$DB" -At -c "SELECT 'orders ' || count(*) || ', ' || min(order_date) || ' ~ ' || max(order_date) FROM orders"
cat <<EOF
완료. 읽기 전용 role 을 만들어 pgxnl 에 대상 이름 'northwind' 로 등록한다(docs/INSTALL.md 6.5 절):
  GRANT CONNECT ON DATABASE $DB TO pgxnl_reader;
  GRANT USAGE ON SCHEMA public TO pgxnl_reader;
  GRANT SELECT ON ALL TABLES IN SCHEMA public TO pgxnl_reader;
EOF
