"""스칼라 서브쿼리 컬럼 개수 검사 — SELECT 목록의 서브쿼리는 컬럼 하나만 (§question_guard 8).

BIRD 465 실측: 질문이 세 가지를 한꺼번에 묻자("how many offers Multiple Provision
Types?" + "List the number of cities" + "how many schools for each city") 모델이
셋을 각각 스칼라 서브쿼리로 만들었는데, 마지막 하나가 2컬럼이었다.

```sql
SELECT
  (SELECT COUNT(*) FROM ...) AS multiple_provision_count,
  (SELECT COUNT(DISTINCT city) FROM ...) AS number_of_cities,
  (SELECT city, COUNT(*) FROM ... GROUP BY city) AS city_school_counts  -- 2컬럼
```

**문법은 맞아서 `generate_sql`을 통과하고 검증 계층도 allowed를 낸다.** 실행에서야
`subquery must return only one column`으로 죽는데 그때는 ReAct 루프가 끝나 모델이
고칠 기회가 없다 — [[execution_errors_in_loop]]와 같은 부류다.

컬럼 근거 검사(`column_rationale`)는 이걸 못 잡는다. 세 컬럼 모두 질문 구절에 대응해
[REQUESTED] ✓ 를 받기 때문이다 — 그쪽은 "질문에 근거가 있나"를 보지 "실행되나"를
보지 않는다. 축이 다르다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MulticolumnScalarSubquery:
    """SELECT 목록에 쓰였는데 컬럼을 둘 이상 반환하는 서브쿼리."""

    label: str
    columns: tuple[str, ...]

    def message(self) -> str:
        cols = ", ".join(self.columns)
        return (
            f"SQL을 다시 작성하세요. SELECT 목록의 서브쿼리 {self.label} 이(가) "
            f"{len(self.columns)}개 컬럼({cols})을 반환합니다 — 실행하면 "
            f"subquery must return only one column 으로 실패합니다. "
            f"SELECT 목록의 서브쿼리는 값 하나만 돌려줄 수 있습니다. "
            f"여러 행·여러 컬럼이 필요하면 서브쿼리로 감싸지 말고 바깥 쿼리 자체를 "
            f"그 형태로 쓰세요 — 질문이 여러 가지를 물어도 SQL 하나가 "
            f"돌려줄 수 있는 표 하나로 답해야 합니다."
        )


def _text(ctx: Any) -> str:
    """원문 그대로 꺼낸다 — `getText()`는 공백을 다 버려 읽을 수 없다."""
    try:
        return ctx.start.getInputStream().getText(ctx.start.start, ctx.stop.stop)
    except Exception:  # noqa: BLE001 — 원문을 못 얻으면 압축된 형태라도 보여준다
        return ctx.getText()


_AS_TAIL = re.compile(r'\bAS\s+("[^"]+"|[A-Za-z_]\w*)\s*$', re.I)


def _alias_of(target_el: Any) -> str | None:
    """`... AS name` 의 name. 문법이 별칭 접근자를 노출하지 않아 원문 끝에서 읽는다."""
    m = _AS_TAIL.search(" ".join(_text(target_el).split()))
    return m.group(1).strip('"') if m else None


def _ancestors(node: Any):
    cur = getattr(node, "parentCtx", None)
    while cur is not None:
        yield cur
        cur = getattr(cur, "parentCtx", None)


def find_multicolumn_scalar_subqueries(stmt: Any) -> list[MulticolumnScalarSubquery]:
    """SELECT 목록에서 2컬럼 이상을 반환하는 서브쿼리를 돌려준다. 없으면 빈 리스트.

    FROM 절의 서브쿼리(`FROM (SELECT a, b ...) AS x`)는 여러 컬럼이 정상이므로
    제외한다 — 조상을 거슬러 올라가 `Target_el`을 `Table_ref`보다 먼저 만나는
    경우만 스칼라 위치로 본다.
    """
    if stmt is None or getattr(stmt, "raw_tree", None) is None:
        return []
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.ir_builder import collect_contexts

    out: list[MulticolumnScalarSubquery] = []
    for sq in collect_contexts(stmt.raw_tree, _P.Select_with_parensContext):
        target_el = None
        for anc in _ancestors(sq):
            if isinstance(anc, (_P.Table_refContext, _P.From_clauseContext)):
                break  # FROM 서브쿼리 — 여러 컬럼이 정상이다
            if isinstance(anc, _P.Target_elContext):
                target_el = anc
                break
        if target_el is None:
            continue

        # sq에 직접 속한 target_list만 센다 — 더 깊이 중첩된 서브쿼리의 것은 제외.
        cols: list[str] = []
        for tl in collect_contexts(sq, _P.Target_listContext):
            owner = None
            for anc in _ancestors(tl):
                if isinstance(anc, _P.Select_with_parensContext):
                    owner = anc
                    break
            if owner is not sq:
                continue
            cols = [_text(t).strip() for t in tl.target_el()]
            break
        if len(cols) <= 1:
            continue

        alias = _alias_of(target_el)
        if alias:
            label = alias
        else:
            text = " ".join(_text(target_el).split())
            label = text if len(text) <= 60 else text[:57] + "..."
        out.append(MulticolumnScalarSubquery(label, tuple(cols)))
    return out
