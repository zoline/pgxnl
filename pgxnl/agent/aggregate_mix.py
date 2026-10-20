"""집계 혼용 검사 — GROUP BY 없이 집계 함수와 집계되지 않은 컬럼을 함께 SELECT (§question_guard 9).

BIRD card_games seq 353(qid 352) 실측: 비율을 구하면서 `CASE` 를 `SUM(...)` 으로 감싸는 것을
빠뜨렸다.

```sql
SELECT CAST(CASE WHEN T1.language = 'Chinese Simplified' THEN 1 ELSE 0 END AS REAL) * 100
       / NULLIF(COUNT(T1.id), 0)          -- T1.language 는 집계 밖, COUNT 는 집계
FROM foreign_data AS T1
```

**문법은 맞아서 `generate_sql`을 통과하고 검증 계층도 allowed를 낸다.** 실행에서야
`column "t1.language" must appear in the GROUP BY clause or be used in an aggregate function`
으로 죽는데 그때는 ReAct 루프가 끝나 모델이 고칠 기회가 없다 — run 358·360 에서 같은 오류.
[[execution_errors_in_loop]]와 같은 부류다.

판정은 보수적이다 — 확실히 실패하는 모양만 잡는다:
  - GROUP BY 가 있는 SELECT 는 보지 않는다(그룹 키 판정은 함수 종속까지 봐야 해 오탐 위험).
  - SELECT 목록에 집계 함수(OVER 없는 COUNT/SUM/AVG/MIN/MAX 등)가 하나 이상 있고,
  - 집계 함수 **밖**에 컬럼 참조가 하나 이상 있을 때. 서브쿼리 안은 그 서브쿼리의 SELECT 로
    따로 본다(바깥 판정에 섞지 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: OVER 없이 쓰이면 집계인 함수. PostgreSQL 내장 집계 중 BIRD·일반 질의에 나오는 것.
_AGGREGATES = frozenset({
    "count", "sum", "avg", "min", "max", "string_agg", "array_agg", "bool_and", "bool_or",
    "every", "stddev", "stddev_pop", "stddev_samp", "variance", "var_pop", "var_samp",
    "json_agg", "jsonb_agg", "percentile_cont", "percentile_disc", "mode",
})


@dataclass(frozen=True)
class AggregateMix:
    """GROUP BY 없는 SELECT 에서 집계 밖에 놓인 컬럼."""

    column: str
    aggregate: str

    def message(self) -> str:
        return (
            f"SQL을 다시 작성하세요. GROUP BY 없이 집계 함수 {self.aggregate} 와 집계되지 않은 "
            f"컬럼 {self.column} 을(를) 같은 SELECT 에 썼습니다 — 실행하면 "
            f'column "{self.column.lower()}" must appear in the GROUP BY clause or be used in an '
            f"aggregate function 으로 실패합니다. 조건부 개수·비율이면 CASE 식을 집계로 감싸세요 "
            f"(예: SUM(CASE WHEN ... THEN 1 ELSE 0 END) 또는 COUNT(CASE WHEN ... THEN id END)). "
            f"그룹별 값이 필요하면 GROUP BY 를 추가하세요."
        )


def _func_name(func_expr: Any) -> str | None:
    app = func_expr.func_application() if hasattr(func_expr, "func_application") else None
    if app is None or app.func_name() is None:
        return None
    return app.func_name().getText().rsplit(".", 1)[-1].strip('"').lower()


def _is_aggregate_call(node: Any, _P: Any) -> str | None:
    """OVER 없는 집계 호출이면 함수 이름(원문 대소문자), 아니면 None."""
    if not isinstance(node, _P.Func_exprContext):
        return None
    if node.over_clause() is not None:
        return None  # 윈도 함수 — 그룹을 만들지 않는다
    name = _func_name(node)
    if name in _AGGREGATES:
        return node.func_application().func_name().getText()
    return None


def _scan(node: Any, _P: Any, in_agg: bool, aggs: list[str], bare: list[str]) -> None:
    """target 하나를 내려가며 집계 호출과 집계 밖 컬럼 참조를 모은다. 서브쿼리는 건너뛴다."""
    if isinstance(node, _P.Select_with_parensContext):
        return
    if isinstance(node, _P.ColumnrefContext):
        if not in_agg:
            bare.append(node.getText())
        return
    agg = _is_aggregate_call(node, _P)
    if agg is not None:
        aggs.append(agg)
        in_agg = True
    for child in getattr(node, "children", None) or []:
        _scan(child, _P, in_agg, aggs, bare)


def find_aggregate_mix(stmt: Any) -> list[AggregateMix]:
    """GROUP BY 없는 SELECT 에서 집계와 비집계 컬럼이 섞였으면 돌려준다. 없으면 빈 리스트."""
    if stmt is None or getattr(stmt, "raw_tree", None) is None:
        return []
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.ir_builder import _first_present, collect_contexts

    out: list[AggregateMix] = []
    stack = [stmt.raw_tree]
    while stack:
        node = stack.pop()
        stack.extend(getattr(node, "children", None) or [])
        if not isinstance(node, _P.Simple_select_pramaryContext):
            continue
        if node.group_clause() is not None:
            continue
        target_list = _first_present(node, "target_list_", "target_list")
        if target_list is None:
            continue
        aggs: list[str] = []
        bare: list[str] = []
        # Target_list_ 노드는 target_el() 접근자가 없다 — 하위에서 모으되, collect_contexts 는
        # 매치한 노드 안으로 내려가지 않으므로 중첩 서브쿼리의 target 은 섞이지 않는다.
        for el in collect_contexts(target_list, _P.Target_elContext):
            _scan(el, _P, False, aggs, bare)
        if aggs and bare:
            out.append(AggregateMix(column=bare[0], aggregate=aggs[0]))
    return out
