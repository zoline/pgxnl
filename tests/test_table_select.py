"""테이블 선택 출력 파싱 (2026-10-15)."""
from pgxnl.agent.table_select import parse_selection

KNOWN = {"posts", "votes", "users"}


def test_parses_json_with_reason_and_drops_unknown():
    sel = parse_selection('설명 {"tables": ["Posts", "votes", "ghost"], "joins": ["votes.userid=users.id"], "reason": "r"} 끝', KNOWN)
    assert sel.tables == ["posts", "votes"] and sel.joins == ["votes.userid=users.id"] and sel.reason == "r"


def test_schema_qualified_and_missing_json():
    assert parse_selection('{"tables": ["cc.users"]}', KNOWN).tables == ["users"]
    assert parse_selection("no json", KNOWN).error == "JSON 없음"
