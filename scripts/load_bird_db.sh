#!/usr/bin/env bash
# BIRD mini-dev PostgreSQL 덤프(BIRD_dev.sql)를 pgxnl 평가용 대상 DB로 적재한다.
#
# 공식 덤프는 11개 데이터베이스의 테이블 75개를 전부 public 스키마에 넣는다. pgxnl 평가는
# db_id 를 스키마 이름으로 쓰므로(card_games.cards 등), 적재 뒤 테이블을 db_id 스키마로 옮긴다.
# ALTER TABLE ... SET SCHEMA 는 그 테이블의 인덱스·제약·소유 시퀀스를 함께 옮기고, 스키마를
# 넘는 FK 는 OID 로 걸려 있어 그대로 유지된다.
#
# 덤프 받는 곳: https://github.com/bird-bench/mini_dev (PostgreSQL 판, 약 1GB)
# 접속 정보는 libpq 환경변수(PGHOST, PGPORT, PGUSER, PGPASSWORD)를 쓴다. 적재 role 은 DB 생성
# 권한이 있어야 하고, pg_stat_statements 확장은 슈퍼유저가 아니면 건너뛴다(경고만).
set -euo pipefail

usage() {
  cat <<'EOF'
사용법: scripts/load_bird_db.sh --dump <BIRD_dev.sql> [--db BIRD]

  --dump PATH   BIRD mini-dev PostgreSQL 덤프 파일
  --db NAME     만들 대상 DB 이름 (기본 BIRD, 이미 있으면 중단)
EOF
}

DUMP="" DB=BIRD
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dump) DUMP=$2; shift ;;
    --db) DB=$2; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage; exit 1 ;;
  esac
  shift
done
[[ -f "$DUMP" ]] || { usage; exit 1; }

PSQL=(psql -X -q -v ON_ERROR_STOP=1)

echo "==> DB 생성: $DB"
createdb "$DB"

echo "==> 덤프 적재 (수 분 걸림) — 원 덤프의 소유자(OWNER TO) 문은 빼고 넣는다"
sed '/^ALTER .* OWNER TO /d' "$DUMP" | "${PSQL[@]}" -d "$DB" >/dev/null

echo "==> 테이블을 db_id 스키마로 이동"
"${PSQL[@]}" -d "$DB" <<'SQL'
BEGIN;
CREATE TEMP TABLE bird_map (db_id text, tbl text) ON COMMIT DROP;
INSERT INTO bird_map
SELECT s, unnest(string_to_array(t, ' ')) FROM (VALUES
 ('california_schools',      'frpm satscores schools'),
 ('card_games',              'cards foreign_data legalities rulings set_translations sets'),
 ('codebase_community',      'badges comments posthistory postlinks posts tags users votes'),
 ('debit_card_specializing', 'customers gasstations products transactions_1k yearmonth'),
 ('european_football_2',     'country league match player player_attributes team team_attributes'),
 ('financial',               'account card client disp district loan order trans'),
 ('formula_1',               'circuits constructorresults constructors constructorstandings drivers driverstandings laptimes pitstops qualifying races results seasons status'),
 ('student_club',            'attendance budget event expense income major member zip_code'),
 ('superhero',               'alignment attribute colour gender hero_attribute hero_power publisher race superhero superpower'),
 ('thrombosis_prediction',   'examination laboratory patient'),
 ('toxicology',              'atom bond connected molecule')
) v(s, t);

SELECT format('CREATE SCHEMA IF NOT EXISTS %I', db_id) FROM (SELECT DISTINCT db_id FROM bird_map) d \gexec
SELECT format('ALTER TABLE public.%I SET SCHEMA %I', tbl, db_id) FROM bird_map \gexec

-- 남은 테이블이 있으면 매핑이 덤프와 안 맞는 것 — 중단
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM pg_tables WHERE schemaname = 'public';
  IF n > 0 THEN RAISE EXCEPTION 'public 에 테이블 % 개가 남음 — 덤프 판이 다른지 확인', n; END IF;
END $$;

-- california_schools: 덤프에는 frpm·schools 의 cdscode 가 UNIQUE 인덱스뿐이라 PK 로 올린다
-- (스키마 표현에서 키 컬럼으로 보이게). satscores 는 덤프에서 이미 PK.
ALTER TABLE california_schools.frpm
  ADD CONSTRAINT frpm_pkey PRIMARY KEY USING INDEX idx_48496_sqlite_autoindex_frpm_1;
ALTER TABLE california_schools.schools
  ADD CONSTRAINT schools_pkey PRIMARY KEY USING INDEX idx_48506_sqlite_autoindex_schools_1;
COMMIT;
SQL

echo "==> pg_stat_statements (JOIN 이력 발견용, 슈퍼유저 필요)"
"${PSQL[@]}" -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" \
  || echo "   건너뜀 — 필요하면 슈퍼유저로 만들고 shared_preload_libraries 에 추가한다"

echo "==> ANALYZE"
"${PSQL[@]}" -d "$DB" -c "SET client_min_messages = error; ANALYZE"

"${PSQL[@]}" -d "$DB" -At -c \
  "SELECT table_schema || ': ' || count(*) AS n FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog','information_schema','public') AND table_type='BASE TABLE'
    GROUP BY table_schema ORDER BY table_schema"
echo "완료. pgxnl 관리 화면에서 대상 '$DB' 로 등록하고 스키마 벡터를 색인한다."
