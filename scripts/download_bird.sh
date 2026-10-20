#!/usr/bin/env bash
# BIRD mini-dev 패키지(minidev.zip, 약 800MB)를 받아 PostgreSQL 덤프 BIRD_dev.sql(약 1GB)만 꺼낸다.
#
# 출처: BIRD 공식 배포(https://github.com/bird-bench/mini_dev 의 "Data Link"). 라이선스 CC BY-SA 4.0.
# 받은 덤프는 scripts/load_bird_db.sh 로 적재한다.
set -euo pipefail

URL="https://bird-bench.oss-cn-beijing.aliyuncs.com/minidev.zip"
MEMBER="minidev/MINIDEV_postgresql/BIRD_dev.sql"
# pgxnl 평가에 쓴 덤프의 SHA-256 — 같은 파일인지 확인용
SHA256="31b1da211849d24a57c9af7636da46a5b82fc8a3ca1542bb3ebd8775e9a31cec"

usage() {
  cat <<'EOF'
사용법: scripts/download_bird.sh [--dir 디렉터리] [--keep-zip]

  --dir DIR     받을 위치 (기본 ./bird_data). 여유 공간 약 2GB 필요
  --keep-zip    다 꺼낸 뒤에도 minidev.zip 을 지우지 않음

끝나면 DIR/BIRD_dev.sql 이 생긴다. 중간에 끊겼으면 다시 실행하면 이어 받는다.
EOF
}

DIR=./bird_data KEEP=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) DIR=$2; shift ;;
    --keep-zip) KEEP=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "알 수 없는 옵션: $1" >&2; usage; exit 1 ;;
  esac
  shift
done

for cmd in curl unzip sha256sum; do
  command -v "$cmd" >/dev/null || { echo "$cmd 가 필요하다" >&2; exit 1; }
done

mkdir -p "$DIR"
OUT="$DIR/BIRD_dev.sql"
ZIP="$DIR/minidev.zip"

if [[ -f "$OUT" ]] && echo "$SHA256  $OUT" | sha256sum -c --status; then
  echo "이미 있다: $OUT (SHA-256 일치)"; exit 0
fi

echo "==> 내려받기: $URL (약 800MB, 끊기면 다시 실행하면 이어 받음)"
curl -fL -C - --retry 3 -o "$ZIP" "$URL"

echo "==> 덤프만 꺼내기: $MEMBER"
unzip -o -j "$ZIP" "$MEMBER" -d "$DIR"

echo "==> 확인 (SHA-256)"
if echo "$SHA256  $OUT" | sha256sum -c --status; then
  echo "   일치"
else
  echo "   경고: SHA-256 이 pgxnl 평가에 쓴 덤프와 다르다 — 배포본이 바뀌었을 수 있다." >&2
  echo "   적재는 되겠지만 평가 결과가 README 와 다를 수 있다." >&2
fi

[[ $KEEP -eq 1 ]] || rm -f "$ZIP"
echo
echo "완료: $OUT"
echo "다음: scripts/load_bird_db.sh --dump $OUT --db BIRD"
