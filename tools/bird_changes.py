"""data/CHANGES.md 를 원본·정정본 데이터셋 비교로 다시 만든다.

    python tools/bird_changes.py           # data/CHANGES.md 갱신
    python tools/bird_changes.py --check   # 다르면 종료 코드 1 (쓰지 않음)

원본 data/bird_minidev_pg.original.json 과 정정본 data/bird_minidev_pg.json 을 seq(파일 안 위치)로 맞춰
question·evidence·SQL 중 바뀐 것을 표와 항목별 전후로 적는다. 정정본을 손댄 뒤 실행한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ORIGINAL = DATA / "bird_minidev_pg.original.json"
CORRECTED = DATA / "bird_minidev_pg.json"
OUT = DATA / "CHANGES.md"
FIELDS = ("question", "evidence", "SQL")

HEADER = """# BIRD mini-dev (PostgreSQL) 정정 내역

`bird_minidev_pg.json` 은 BIRD mini-dev PostgreSQL 판(`bird_minidev_pg.original.json`)을 pgxnl 평가 중에 정정한 것이다.
정정 원칙: 질문이 맞고 gold SQL 이 틀리면 gold 를 고친다. 질문·evidence 가 성립하지 않거나 오기가 있을 때만 그쪽을 고친다.
질문을 gold 에 맞춰 굽히지 않는다. 해석이 갈리는 문항은 고치지 않는다.
"""


def render() -> str:
    original = json.loads(ORIGINAL.read_text(encoding="utf-8"))
    corrected = json.loads(CORRECTED.read_text(encoding="utf-8"))
    if len(original) != len(corrected):
        raise SystemExit(f"문항 수가 다르다: 원본 {len(original)}, 정정본 {len(corrected)}")
    changed = []
    for seq, (a, b) in enumerate(zip(original, corrected)):
        if a.get("question_id") != b.get("question_id"):
            raise SystemExit(f"seq {seq}: question_id 가 다르다({a.get('question_id')} / {b.get('question_id')}) — 순서를 바꾸지 않는다")
        fields = [f for f in FIELDS if a.get(f) != b.get(f)]
        if fields:
            changed.append((seq, a, b, fields))

    lines = [HEADER, f"정정 문항 {len(changed)}개 (seq 는 파일 안 위치, 0부터).", "",
             "| seq | db_id | question_id | 바뀐 항목 |", "|---|---|---|---|"]
    lines += [f"| {seq} | {a['db_id']} | {a['question_id']} | {', '.join(fields)} |" for seq, a, _, fields in changed]
    lines += ["", "## 항목별 전후", ""]
    for seq, a, b, fields in changed:
        lines.append(f"### seq {seq} · {a['db_id']} · qid {a['question_id']}")
        for f in fields:
            lines.append(f"- **{f}** 원본: `{a.get(f)}`")
            lines.append(f"- **{f}** 정정: `{b.get(f)}`")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="CHANGES.md 가 최신인지 확인만 (다르면 종료 코드 1)")
    args = ap.parse_args()
    text = render()
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if args.check:
        sys.exit(0 if current == text else 1)
    if current != text:
        OUT.write_text(text, encoding="utf-8")
        print(f"{OUT.relative_to(DATA.parent)} 갱신")
    else:
        print(f"{OUT.relative_to(DATA.parent)} 변경 없음")


if __name__ == "__main__":
    main()
