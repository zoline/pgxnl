"""Northwind 골든 세트(docs/northwind_golden_set_v2.json) → 평가 데이터셋(data/northwind_pg.json).

v2 는 질문만 보고 출력 컬럼·순서를 알 수 있게 다시 쓴 판이다(원칙 P1~P8, docs/northwind_golden_set_v2.md).

    python tools/northwind_dataset.py                 # 변환만
    python tools/northwind_dataset.py --verify DSN    # 변환 + 각 gold 를 DB 에서 실행해 기대 결과와 대조

Northwind 데이터(1996-07 ~ 1998-05)는 +28년 옮겨 2024-07 ~ 2026-05 로 적재한다(scripts/load_northwind_db.sh).
그레고리력은 28년마다 요일·윤년이 같으므로 연·월·요일 집계 결과가 바뀌지 않는다 — 질문·SQL 의 연도만
1996→2024, 1997→2025, 1998→2026 으로 바꾸면 된다. 기준일(오늘)은 2026-05-06(데이터 마지막 주문일).

필드 대응(BIRD 평가 형식):
  question=ko(한글 질문), evidence=hint(+ 금액 반올림 안내), SQL=sql, db_id='public',
  difficulty=L1·L2 simple / L3 moderate / L4 challenging, question_id=골든 세트 id(L1-01 …)
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "northwind_golden_set_v2.json"
OUT = ROOT / "data" / "northwind_pg.json"
YEAR_SHIFT = 28
DB_ID = "public"
DIFFICULTY = {1: "simple", 2: "simple", 3: "moderate", 4: "challenging"}
ROUND_NOTE = "금액(매출 등)은 소수 둘째 자리로 반올림한다."
DAYS_NOTE = "평균 일수는 소수 첫째 자리로 반올림한다."   # v2 원칙 P8 — 질문만 보고 자릿수를 알 수 있게


def shift_years(text: str) -> str:
    # \b 는 쓰지 않는다 — 한글도 단어 문자라 "1997년" 의 7 과 년 사이에 경계가 없다
    return re.sub(r"(?<!\d)(199[6-8])(?!\d)", lambda m: str(int(m.group(1)) + YEAR_SHIFT), text)


def convert(src: dict) -> list[dict]:
    items = []
    for q in src["questions"]:
        sql = shift_years(q["sql"])
        evidence = [q["hint"]] if q.get("hint") else []
        # 자릿수는 gold 의 ROUND(…, n) 로 가른다 — 2 는 금액·비율, 1 은 평균 일수(seq 31)뿐이다
        digits = set(re.findall(r",\s*(\d)\s*\)\s*AS\s", sql, re.IGNORECASE)) if re.search(r"ROUND\s*\(", sql, re.I) else set()
        if "2" in digits:
            evidence.append(ROUND_NOTE)
        if "1" in digits:
            evidence.append(DAYS_NOTE)
        items.append({
            "question_id": q["id"],
            "db_id": DB_ID,
            "question": shift_years(q["ko"]),
            "evidence": " ".join(evidence),
            "SQL": sql,
            "difficulty": DIFFICULTY[q["level"]],
        })
    return items


def _norm(v):
    """기대 결과 비교용: 날짜는 +28년 옮긴 값과, 연도 정수는 옮긴 연도와 맞춘다."""
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()[:10]
    if isinstance(v, (Decimal, float)):
        return round(float(v), 5)   # real 컬럼 오차 — pgxnl EX 와 같게 소수 5자리
    return v


def _expected_shifted(v):
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d\d-\d\d.*", v):   # 날짜 열은 전부 +28년 적재(입사일 1992~ 포함)
        return str(int(v[:4]) + YEAR_SHIFT) + v[4:10]
    if isinstance(v, int) and 1996 <= v <= 1998:                       # 연도 집계 열
        return v + YEAR_SHIFT
    if isinstance(v, float):
        return round(v, 5)
    return v


def _same_row(got: list, want: list) -> bool:
    """real 컬럼(가격·운임)은 float 오차가 있어 소수 셋째 자리까지만 본다(문서의 기대값은 소수 둘째 자리)."""
    if len(got) != len(want):
        return False
    for g, w in zip(got, want):
        if isinstance(g, float) and isinstance(w, (int, float)):
            if abs(g - w) > 1e-3:
                return False
        elif g != w:
            return False
    return True


async def verify(dsn: str, src: dict, items: list[dict]) -> int:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    bad = 0
    try:
        for q, item in zip(src["questions"], items):
            rows = await conn.fetch(item["SQL"])
            got = [[_norm(v) for v in r.values()] for r in rows]
            exp = q["expected"]
            want = [[_expected_shifted(v) for v in row] for row in exp["rows"]]
            ok = len(rows) == exp["row_count"] and len(got) >= len(want) and all(
                _same_row(g, w) for g, w in zip(got, want))
            if not ok:
                bad += 1
                print(f"✗ {item['question_id']}: rows {len(rows)} vs {exp['row_count']}\n   got  {got[:3]}\n   want {want[:3]}")
        print(f"검증: {len(items) - bad}/{len(items)} 일치")
    finally:
        await conn.close()
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", metavar="DSN", help="northwind DB 에 접속해 gold 결과를 기대값과 대조")
    args = ap.parse_args()
    src = json.loads(SRC.read_text(encoding="utf-8"))
    items = convert(src)
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(items)}문항")
    if args.verify:
        raise SystemExit(1 if asyncio.run(verify(args.verify, src, items)) else 0)


if __name__ == "__main__":
    main()
