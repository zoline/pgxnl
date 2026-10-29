"""pgxnl MCP 서버 — 도구 정의와 진입점.

역할 분담(2026-10-28 결정): pgxnl 이 SQL 생성·검증·실행까지, 결과 해석은 MCP 클라이언트
LLM 이 한다. 그래서 ask 는 pgxnl 의 요약 단계를 끄고(summarize=false) SQL 과 결과 행을
돌려준다. 실행은 언제나 pgxnl 을 거친다 — 클라이언트가 DB 에 직접 붙으면 읽기 전용·비용
상한·감사 기록을 우회하게 된다.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from pgxnl_mcp import client
from pgxnl_mcp.client import Config, PgxnlError

# 클라이언트 LLM 컨텍스트를 지키는 상한. pgxnl 서버도 실행 결과를 따로 자른다(기본 50행).
MAX_ROWS = int(os.environ.get("PGXNL_MCP_MAX_ROWS", "50"))
MAX_CHARS = int(os.environ.get("PGXNL_MCP_MAX_CHARS", "20000"))

mcp = FastMCP(
    "pgxnl",
    instructions=(
        "pgxnl 은 PostgreSQL 에 자연어로 질의하는 서비스다. 데이터 질문은 먼저 ask 를 쓴다 — "
        "pgxnl 이 용어집·규칙·조인 경로를 붙여 SQL 을 만들고 검증·실행해 결과 행을 돌려준다. "
        "결과 해석·요약은 네가 한다. target 이름은 list_targets 로 확인한다. "
        "SQL 을 직접 고쳐 실행할 때는 run_sql 을 쓴다(같은 검증을 거친다)."
    ),
)

_cfg: Config | None = None


def cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config.from_env()
    return _cfg


def _cap_rows(rows: list[dict[str, Any]] | None) -> dict[str, Any]:
    rows = rows or []
    shown = rows[:MAX_ROWS]
    # 행 수 상한만으로는 넓은 행(긴 텍스트 컬럼)이 컨텍스트를 터뜨린다 — 글자 수로도 자른다.
    while shown and len(json.dumps(shown, ensure_ascii=False, default=str)) > MAX_CHARS:
        shown = shown[: max(1, len(shown) // 2)] if len(shown) > 1 else []
    return {"row_count": len(rows), "rows": shown, "truncated": len(shown) < len(rows)}


@mcp.tool()
async def list_targets() -> dict[str, Any]:
    """질의할 수 있는 대상 DB(target) 목록."""
    return await client.get(cfg(), "/api/targets")


@mcp.tool()
async def list_schemas(target: str) -> dict[str, Any]:
    """대상 DB 의 스키마 목록."""
    return await client.get(cfg(), f"/api/targets/{target}/schemas")


@mcp.tool()
async def describe_schema(target: str, search: str = "", schema: str = "") -> str:
    """테이블·컬럼(타입, PK, FK, 주석)을 조회한다.

    search: 테이블·컬럼 이름이나 주석에 들어간 낱말로 좁힌다(대소문자 무시).
    schema: 특정 스키마만. 큰 DB 는 search 나 schema 로 좁혀서 부를 것.
    """
    data = await client.get(cfg(), f"/api/targets/{target}/browse", {"search": search})
    lines: list[str] = []
    for t in data.get("tables", []):
        if schema and t["schema"] != schema:
            continue
        head = f"{t['schema']}.{t['table']}"
        if t.get("comment"):
            head += f"  -- {t['comment']}"
        lines.append(head)
        for c in t["columns"]:
            col = f"  {c['name']} {c['type']}"
            if c.get("is_pk"):
                col += " PK"
            if c.get("fk"):
                col += f" -> {c['fk']['table']}.{c['fk']['column']}"
            if c.get("comment"):
                col += f"  -- {c['comment']}"
            lines.append(col)
    text = "\n".join(lines) or "일치하는 테이블이 없습니다."
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "\n... (잘림 — search 나 schema 로 좁혀서 다시 부르세요)"
    return text


@mcp.tool()
async def ask(
    target: str, question: str, ctx: Context, schema: str = "public",
    evidence: str | None = None, sql_only: bool = False,
) -> dict[str, Any]:
    """자연어 질문을 pgxnl 이 SQL 로 만들고 검증·실행해 결과 행을 돌려준다(요약은 하지 않는다).

    수십 초~1분 이상 걸린다. evidence: 질문에 덧붙일 업무 정의(예: "매출 = 단가*수량*(1-할인)").
    sql_only=true 면 실행하지 않고 검증을 통과한 SQL 만 돌려준다 — 실행은 run_sql 로.
    """
    async def on_status(message: str) -> None:
        await ctx.info(message)

    body = {
        "target": target, "question": question, "schema": schema, "evidence": evidence,
        "execute": not sql_only, "summarize": False,
    }
    result = await client.ask(cfg(), body, on_status)
    steps = result.get("sql_steps") or []
    if not steps:
        # 거부·실행 실패·SQL 미생성 — 사유는 answer 에 담겨 온다.
        return {"ok": False, "reason": result.get("answer") or "SQL 을 만들지 못했습니다"}
    out: dict[str, Any] = {"ok": True, "sql": steps[-1]["sql"], "from_cache": result.get("from_cache", False)}
    if not sql_only:
        out.update(_cap_rows(result.get("rows")))
    return out


@mcp.tool()
async def run_sql(target: str, sql: str, schema: str = "public") -> dict[str, Any]:
    """SQL 을 pgxnl 검증 계층(읽기 전용·비용 상한·감사)을 거쳐 실행한다."""
    r = await client.post(cfg(), "/api/analyze/sql", {"target": target, "sql": sql, "schema_name": schema})
    if r.get("rejected"):
        return {"ok": False, "sql": r.get("sql"), "reason": r.get("reason")}
    return {"ok": True, "sql": r.get("sql"), **_cap_rows(r.get("rows"))}


@mcp.tool()
async def explain(target: str, sql: str, schema: str = "public", analyze: bool = False) -> Any:
    """실행계획(EXPLAIN FORMAT JSON). analyze=true 면 실제로 실행해 측정한다(읽기 전용 트랜잭션)."""
    return await client.post(
        cfg(), f"/api/targets/{target}/explain", {"sql": sql, "analyze": analyze, "schema_name": schema},
    )


@mcp.tool()
async def find_join_path(target: str, from_table: str, to_table: str, schema: str = "") -> dict[str, Any]:
    """두 테이블을 잇는 JOIN 경로(승인된 관계만)."""
    return await client.get(
        cfg(), f"/api/targets/{target}/join-path",
        {"from_table": from_table, "to_table": to_table, "schema": schema},
    )


@mcp.tool()
async def similar_queries(target: str, question: str, schema: str | None = None, limit: int = 5) -> dict[str, Any]:
    """승인된 검증 질의(질문+SQL) 가운데 비슷한 것. 직접 SQL 을 쓸 때 참고용."""
    data = await client.get(
        cfg(), f"/api/targets/{target}/verified-queries",
        {"q": question, "schema_name": schema, "approved_only": "true", "limit": limit},
    )
    return {
        "items": [
            {"question": i["question"], "sql": i["sql"], "schema": i["schema_name"], "score": i.get("score")}
            for i in data.get("items", [])
        ]
    }


def main() -> None:
    p = argparse.ArgumentParser(prog="pgxnl-mcp", description=__doc__.splitlines()[0])
    p.add_argument("--transport", choices=["stdio"], default="stdio",
                   help="지금은 stdio 만 — 사용자 PC 에서 띄워 pgxnl API 를 HTTPS 로 부른다")
    p.parse_args()
    try:
        cfg()
    except PgxnlError as exc:
        raise SystemExit(f"pgxnl-mcp: {exc}") from exc
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
