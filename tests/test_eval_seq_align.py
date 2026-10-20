"""몇 문항만 올린 파일도 seq 를 기본 데이터셋 번호로 맞춘다 (2026-10-14)."""
from __future__ import annotations

import json

from pgxnl.agent.evaluation.bird import align_seq_to_default, parse_bird_json


def _row(db, qid):
    return {"db_id": db, "question_id": qid, "question": "q", "SQL": "SELECT 1"}


def test_기본_데이터셋_번호를_쓴다(tmp_path) -> None:
    default = tmp_path / "d.json"
    default.write_text(json.dumps([_row("a", 1), _row("b", 7), _row("b", 9)]))
    items = align_seq_to_default(parse_bird_json([_row("b", 9), _row("b", 7)]), default)
    assert [it["seq"] for it in items] == [2, 1]


def test_없는_문항은_파일_위치(tmp_path) -> None:
    default = tmp_path / "d.json"
    default.write_text(json.dumps([_row("a", 1)]))
    items = align_seq_to_default(parse_bird_json([_row("x", 5), _row("a", 1)]), default)
    assert [it["seq"] for it in items] == [0, 0]


def test_실제_데이터셋_california_27은_446() -> None:
    items = align_seq_to_default(parse_bird_json([_row("california_schools", 27)]))
    assert items[0]["seq"] == 446
