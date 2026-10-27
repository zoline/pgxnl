"""별칭 스코프 검사 — 바깥 쿼리가 서브쿼리 안의 별칭을 참조하는지 (§question_guard 6).

BIRD 454 실측: 모델이 서브쿼리에 `AS T3`을 제대로 붙이고 `WHERE T3.rnk`도 맞게 썼는데,
`SELECT`만 안쪽 별칭으로 남겼다.

```sql
SELECT T1.school          -- T1은 서브쿼리 안에만 있다
FROM ( SELECT T1.school, RANK() OVER (...) AS rnk
       FROM schools AS T1 JOIN satscores AS T2 ON ... ) AS T3
WHERE T3.rnk <= 5
```

**문법은 맞아서 `generate_sql`을 통과하고, 검증 계층은 별칭 스코프를 안 봐서 allowed가
난다.** 실행에서야 `missing FROM-clause entry for table "t1"`으로 죽는데 그때는 ReAct
루프가 이미 끝나 모델이 고칠 기회가 없다 — 최근 22개 run에서 13건이 이 오류였다.

`window_misuse_clause`와 같은 자리(`_generate_sql`)에서 되돌려 모델이 고치게 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UnresolvedAlias:
    """바깥에서 참조했지만 그 스코프에 없는 별칭."""

    alias: str
    visible: tuple[str, ...]

    def message(self) -> str:
        seen = ", ".join(self.visible) if self.visible else "(없음)"
        return (
            f"SQL을 다시 작성하세요. {self.alias} 을(를) 참조하는데 그 별칭은 다른 서브쿼리나 CTE "
            f"**안에서만** 정의됩니다 — 실행하면 "
            f'missing FROM-clause entry for table "{self.alias}" 로 실패합니다. '
            f"그 자리에서 쓸 수 있는 별칭은 {seen} 입니다. 서브쿼리·CTE가 내보낸 컬럼을 "
            f"그 별칭으로 참조하세요."
        )


def find_unresolved_aliases(stmt: Any) -> list[UnresolvedAlias]:
    """참조한 자리에서 보이지 않는 별칭을 돌려준다. 없으면 빈 리스트.

    토큰 인덱스 범위로 스코프를 가른다 — 서브쿼리 `( SELECT … )` 와 CTE 본문 `WITH x AS ( … )` 가
    각각 스코프다. 한 자리에서 보이는 별칭은 그 자리를 **감싸는** 스코프(자기 자신과 바깥들)에서
    선언된 것뿐이다. 형제 스코프(다른 CTE)나 안쪽 스코프의 별칭은 보이지 않는다.
    `alias_to_table`은 평면 dict라 이 구분을 못 한다.

    CTE 본문은 문법상 `select_with_parens` 가 아니다 — 처음엔 서브쿼리만 스코프로 봐서 Northwind v2
    run 565 의 seq 27(CTE 안의 `c` 를 바깥 SELECT 에서 참조)·33(한 CTE 의 `od` 를 다른 CTE 에서
    참조)을 놓쳤다. 둘 다 실행에서 죽었다.
    """
    if stmt is None or getattr(stmt, "raw_tree", None) is None:
        return []
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.ir_builder import collect_contexts

    scopes = [
        (c.start.tokenIndex, c.stop.tokenIndex)
        for c in collect_contexts(stmt.raw_tree, _P.Select_with_parensContext)
    ]
    for cte in collect_contexts(stmt.raw_tree, _P.Common_table_exprContext):
        body = cte.preparablestmt() if hasattr(cte, "preparablestmt") else None
        if body is not None:
            scopes.append((body.start.tokenIndex, body.stop.tokenIndex))
    if not scopes:
        return []  # 스코프가 하나뿐이면 이 오류가 날 수 없다
    root = (-1, 1 << 30)

    def innermost(idx: int) -> tuple[int, int]:
        holding = [s for s in scopes if s[0] <= idx <= s[1]]
        return min(holding, key=lambda s: s[1] - s[0]) if holding else root

    def encloses(scope: tuple[int, int], idx: int) -> bool:
        return scope[0] <= idx <= scope[1]

    declared: dict[str, list[tuple[int, int]]] = {}
    for a in collect_contexts(stmt.raw_tree, _P.Alias_clauseContext):
        colid = a.colid() if hasattr(a, "colid") else None
        if colid is None:
            continue
        name = colid.getText().strip('"').lower()
        declared.setdefault(name, []).append(innermost(a.start.tokenIndex))

    # FROM에 직접 쓴 테이블 이름(별칭 없이)도 그 스코프에서 참조 가능하다.
    for r in collect_contexts(stmt.raw_tree, _P.Relation_exprContext):
        qn = r.qualified_name() if hasattr(r, "qualified_name") else None
        if qn is None:
            continue
        name = qn.getText().rsplit(".", 1)[-1].strip('"').lower()
        declared.setdefault(name, []).append(innermost(r.start.tokenIndex))

    out: list[UnresolvedAlias] = []
    seen: set[str] = set()
    for ref in collect_contexts(stmt.raw_tree, _P.ColumnrefContext):
        colid = ref.colid() if hasattr(ref, "colid") else None
        if colid is None or ref.indirection() is None:
            continue  # 한정되지 않은 컬럼(`school`)은 스코프 판정 대상이 아니다
        alias = colid.getText().strip('"').lower()
        idx = ref.start.tokenIndex
        if alias in seen or alias not in declared:
            continue  # 선언이 아예 없으면 다른 검사(존재하지 않는 별칭)의 몫이다
        if any(encloses(s, idx) for s in declared[alias]):
            continue
        seen.add(alias)
        visible = sorted(n for n, ss in declared.items() if any(encloses(s, idx) for s in ss))
        out.append(UnresolvedAlias(alias, tuple(visible)))
    return out
