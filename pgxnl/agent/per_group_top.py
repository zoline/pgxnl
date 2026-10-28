"""그룹별 1위를 묻는데 전체를 LIMIT 1 로 자른 SQL 을 찾는다 — 조언형 가드(2026-10-28, northwind 전용으로 시작).

"국가별로 매출 1위 고객사…"(Northwind L4-06)를 모델이 `GROUP BY country, company_name ORDER BY revenue DESC LIMIT 1`
로 풀면 국가마다 한 행이 아니라 전체 1위 한 행만 나온다. 같은 설정에서도 run 마다 갈렸다(568·589·590 ✗, 578·586 ✓) —
규칙이 하나 늘 때마다 프롬프트가 흔들려 문구로는 못 잡는다.

"카테고리별 매출이 가장 높은 카테고리" 처럼 그룹 하나를 고르는 질문은 GROUP BY 키가 하나라 걸리지 않는다 —
그룹 키(국가) 안에서 다른 대상(고객사)을 고를 때만 GROUP BY 키가 둘 이상이 된다. 코드가 고치지 않고 모델에게 알린다.
"""
from __future__ import annotations

import re
from typing import Any

_PER_GROUP = re.compile(r"[가-힣A-Za-z]별|\b(each|per|for every)\b", re.I)
_TOP = re.compile(r"1위|1등|가장|최고|최대|최다|최소|최저|\b(top|highest|lowest|most|least|best)\b", re.I)

MESSAGE = (
    "질문이 그룹마다 1위를 묻는 것 같은데, SQL 이 전체 결과를 LIMIT 1 로 잘라 한 행만 나옵니다. "
    "그룹마다 한 행이 필요하면 ROW_NUMBER() 또는 RANK() OVER (PARTITION BY 그룹 키 ORDER BY …) 로 순위를 매기고 "
    "순위 1 만 남기세요. 전체에서 하나만 묻는 질문이면 그대로 두세요."
)


def find_per_group_top(stmt: Any, question: str) -> bool:
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.base import SqlKind
    from pgxnl.parsing.ir_builder import collect_contexts

    q = question or ""
    if not (_PER_GROUP.search(q) and _TOP.search(q)):
        return False
    if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
        return False
    outer = next(iter(collect_contexts(stmt.raw_tree, _P.Select_no_parensContext)), None)
    if outer is None:
        return False
    limit = next((ch for ch in outer.children or [] if isinstance(ch, _P.Select_limitContext)), None)
    if limit is None or re.sub(r"\s", "", limit.getText()).lower() not in ("limit1", "fetchfirst1rowsonly", "fetchfirst1rowonly"):
        return False
    prims = collect_contexts(outer.select_clause(), _P.Simple_select_pramaryContext)
    if len(prims) != 1 or prims[0].group_clause() is None:
        return False
    return len(collect_contexts(prims[0].group_clause(), _P.Group_by_itemContext)) >= 2
