"""그룹별 집계만 여러 행 내는 SQL 을 찾는다 — 조언형 가드(2026-10-16, codebase_community 전용으로 시작).

`SELECT SUM(u.upvotes)/COUNT(*), AVG(u.age) FROM posts p JOIN users u … GROUP BY p.owneruserid HAVING COUNT(*) > 10`
처럼 바깥에 GROUP BY 가 있고 SELECT 에 그룹 키 없이 집계값만 있으면, 그룹마다 이름 없는 숫자 한 행씩이 나온다.
질문이 그 그룹들 **전체에 대한 값 하나**(평균, 개수)를 묻는다면 마지막 집계가 빠진 것이다 — 320(How many users),
323(average of …) 이 그랬다. 그룹별 답을 원하는 질문(each/per/every)은 건드리지 않는다.

코드가 고치지 않고 모델에게 알린다 — 감쌀 집계가 COUNT 인지 AVG 인지는 질문마다 다르다.
"""
from __future__ import annotations

import re
from typing import Any

_AGG = re.compile(r"\b(count|sum|avg|min|max)\s*\(", re.I)
_PER_GROUP = re.compile(r"\b(each|per|every|respectively)\b", re.I)

MESSAGE = (
    "SELECT 에 그룹 키 없이 집계값만 있고 바깥에 GROUP BY 가 있어, 그룹마다 한 행씩 여러 행이 나옵니다. "
    "질문이 그 그룹들 전체에 대한 값 하나를 묻는다면, 그룹을 서브쿼리에서 먼저 고른 뒤 바깥에서 한 번 더 집계하세요."
)


def find_grouped_rows(stmt: Any, question: str) -> bool:
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.base import SqlKind
    from pgxnl.parsing.ir_builder import _first_present, collect_contexts

    if _PER_GROUP.search(question or ""):
        return False
    if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
        return False
    outer = next(iter(collect_contexts(stmt.raw_tree, _P.Select_no_parensContext)), None)
    if outer is None or _first_present(outer, "sort_clause_", "sort_clause") is not None:
        return False
    if any(ch.getText().lower().startswith(("limit", "fetch")) for ch in outer.children or []):
        return False  # 상위 N 개를 고르는 질의는 그룹별 행이 정상이다
    prims = collect_contexts(outer.select_clause(), _P.Simple_select_pramaryContext)
    if len(prims) != 1 or prims[0].group_clause() is None:
        return False
    target_list = _first_present(prims[0], "target_list_", "target_list")
    items = collect_contexts(target_list, _P.Target_elContext) if target_list is not None else []
    return bool(items) and all(_AGG.search(el.getText()) for el in items)
