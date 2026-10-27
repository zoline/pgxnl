"""1:N 조인으로 부푼 COUNT 를 찾는다 — 조언형 가드(2026-10-27, northwind 로 시작).

`COUNT(o.order_id)` 처럼 1쪽 테이블의 키를 세면서 그 테이블을 N쪽 자식(order_details)과 조인하면,
1쪽 한 행이 자식 행 수만큼 반복돼 개수가 부푼다(팬아웃). 실측: Northwind v2 seq 17 — 직원별 주문 건수가
COUNT(DISTINCT) 없이 2.6배로 나왔다.

**판정하지 않는다.** 같은 SQL 모양이라도 질문이 1쪽의 개수("주문 몇 건")를 물으면 DISTINCT 가 맞고,
N쪽의 개수("게시물 몇 개" — BIRD 309 는 users.Id 를 세지만 답은 게시물 수)를 물으면 그대로가 맞다.
BIRD 500 gold 실측: 팬아웃이 실제로 생기는 33건 중 15건이 DISTINCT, 18건이 중복 유지. 그래서 코드는
"이 조인으로 행이 반복된다"는 사실만 알리고, 어느 쪽인지는 모델이 질문을 보고 정한다.

1·N 판정은 대상 DB 카탈로그로 한다: 컬럼 하나짜리 UNIQUE 인덱스(PK 포함)가 있거나 pg_stats 의
n_distinct = -1 이면 유일. 통계도 인덱스도 없으면 판단 불가로 보고 알리지 않는다.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pgxnl.parsing.ir import PredicateNode, QueryIR

#: (테이블, 컬럼) → True 유일 / False 중복 있음 / None 모름
UniqueLookup = Callable[[str, str], Awaitable[bool | None]]

_COUNT = re.compile(r'\bcount\s*\(\s*(distinct\s+)?([A-Za-z_][\w$]*)\s*\.\s*("[^"]+"|[\w$]+)\s*\)', re.I)
_COL = re.compile(r'^\s*([A-Za-z_][\w$]*)\s*\.\s*("[^"]+"|[\w$]+)\s*$')


@dataclass(frozen=True)
class FanoutCount:
    count_expr: str
    table: str
    child_table: str
    on: str

    def message(self) -> str:
        return (
            f"{self.count_expr} 는 {self.table} 의 키를 세지만, {self.child_table} 를 {self.on} 로 조인해서 "
            f"{self.table} 한 행이 {self.child_table} 행 수만큼 반복됩니다(1:N). 질문이 {self.table} 의 개수를 "
            f"묻는다면 COUNT(DISTINCT …)로 세고, {self.child_table} 행의 개수를 묻는다면 그대로 두세요."
        )


def _name(raw: str) -> str:
    return raw.strip().strip('"')


def _equalities(node: PredicateNode | None) -> list[tuple[str, str, str, str]]:
    """ON 절의 `a.x = b.y` 를 (a, x, b, y) 로. AND 아래만 본다."""
    if node is None:
        return []
    out = []
    for leaf in node.flatten_and():
        if leaf.op != "CMP" or leaf.comparator != "=":
            continue
        left, right = _COL.match(leaf.left or ""), _COL.match(leaf.right or "")
        if left and right:
            out.append((left.group(1).lower(), _name(left.group(2)), right.group(1).lower(), _name(right.group(2))))
    return out


async def find_fanout_counts(
    ir: QueryIR, *, alias_to_table: dict[str, str], is_unique: UniqueLookup,
) -> list[FanoutCount]:
    if ir is None or not ir.joins or ir.set_operation:
        return []
    aliases = {a.lower(): t for a, t in alias_to_table.items()}
    grouped = {g.replace(" ", "").lower() for g in ir.group_by or []}
    edges = [e for j in ir.joins for e in _equalities(j.on)]

    out: list[FanoutCount] = []
    for item in ir.select_items:
        for m in _COUNT.finditer(item.expr or ""):
            if m.group(1):
                continue  # 이미 DISTINCT
            alias, col = m.group(2).lower(), _name(m.group(3))
            table = aliases.get(alias)
            if table is None or f"{alias}.{col}".lower() in grouped:
                continue  # 키로 묶었으면 그룹마다 N쪽 행을 세는 것이 의도다
            if await is_unique(table, col) is not True:
                continue
            for a, x, b, y in edges:
                if alias not in (a, b) or a == b:
                    continue
                other, other_col = (b, y) if a == alias else (a, x)
                child = aliases.get(other)
                if child is None or await is_unique(child, other_col) is not False:
                    continue
                own = x if a == alias else y
                out.append(FanoutCount(
                    count_expr=m.group(0), table=table, child_table=child,
                    on=f"{alias}.{own} = {other}.{other_col}",
                ))
                break
            if out:
                return out
    return out
