"""디버그 때만 도구에 이유 칸 (2026-10-15)."""
from pgxnl.agent.orchestrator import TOOL_SCHEMAS, tools_with_reason


def test_reason_added_and_required_except_finalize():
    tools = {t["name"]: t for t in tools_with_reason(TOOL_SCHEMAS)}
    gen = tools["generate_sql"]["input_schema"]
    assert "reason" in gen["properties"] and "reason" in gen["required"]
    assert "reason" not in tools["finalize"]["input_schema"]["properties"]


def test_original_schemas_untouched():
    tools_with_reason(TOOL_SCHEMAS)
    assert all("reason" not in t["input_schema"].get("properties", {}) for t in TOOL_SCHEMAS)
