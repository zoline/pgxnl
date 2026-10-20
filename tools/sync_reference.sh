#!/usr/bin/env bash
# 기준 정보를 저장소 파일로 맞춘다 — 커밋 전에 실행(또는 .githooks/pre-commit 이 자동 실행).
#   시스템 DB 의 규칙·용어집·JOIN 그래프·gold 결함 → seed/*.json   (tools/seed_export.py)
#   정정본 데이터셋 data/bird_minidev_pg.json     → data/CHANGES.md (tools/bird_changes.py)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY=.venv/bin/python; [[ -x $PY ]] || PY=python3
"$PY" tools/seed_export.py
"$PY" tools/bird_changes.py
git status --short -- seed data/CHANGES.md
