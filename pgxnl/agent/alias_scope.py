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
            f"SQL을 다시 작성하세요. 바깥 쿼리가 {self.alias} 을(를) 참조하는데 그 별칭은 "
            f"서브쿼리 **안에서만** 정의됩니다 — 실행하면 "
            f'missing FROM-clause entry for table "{self.alias}" 로 실패합니다. '
            f"바깥에서 쓸 수 있는 별칭은 {seen} 입니다. 서브쿼리가 내보낸 컬럼을 "
            f"그 별칭으로 참조하세요."
        )


def find_unresolved_aliases(stmt: Any) -> list[UnresolvedAlias]:
    """서브쿼리 안에서만 선언된 별칭을 바깥이 참조하면 돌려준다. 없으면 빈 리스트.

    토큰 인덱스 범위로 스코프를 가른다 — 서브쿼리 노드의 [start, stop] 안에 있으면
    안쪽, 밖이면 바깥이다. `alias_to_table`은 평면 dict라 이 구분을 못 한다.
    """
    if stmt is None or getattr(stmt, "raw_tree", None) is None:
        return []
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.ir_builder import collect_contexts

    subqueries = [
        (c.start.tokenIndex, c.stop.tokenIndex)
        for c in collect_contexts(stmt.raw_tree, _P.Select_with_parensContext)
    ]
    if not subqueries:
        return []  # 서브쿼리가 없으면 스코프가 하나뿐이라 이 오류가 날 수 없다

    def inside(idx: int) -> bool:
        return any(lo <= idx <= hi for lo, hi in subqueries)

    inner: set[str] = set()
    outer: set[str] = set()
    for a in collect_contexts(stmt.raw_tree, _P.Alias_clauseContext):
        colid = a.colid() if hasattr(a, "colid") else None
        if colid is None:
            continue
        name = colid.getText().strip('"').lower()
        (inner if inside(a.start.tokenIndex) else outer).add(name)

    # FROM에 직접 쓴 테이블 이름(별칭 없이)도 바깥에서 참조 가능하다.
    for r in collect_contexts(stmt.raw_tree, _P.Relation_exprContext):
        qn = r.qualified_name() if hasattr(r, "qualified_name") else None
        if qn is None:
            continue
        name = qn.getText().rsplit(".", 1)[-1].strip('"').lower()
        (inner if inside(r.start.tokenIndex) else outer).add(name)

    out: list[UnresolvedAlias] = []
    seen: set[str] = set()
    for ref in collect_contexts(stmt.raw_tree, _P.ColumnrefContext):
        if inside(ref.start.tokenIndex):
            continue  # 안쪽 참조는 안쪽 별칭을 써도 된다
        colid = ref.colid() if hasattr(ref, "colid") else None
        if colid is None or ref.indirection() is None:
            continue  # 한정되지 않은 컬럼(`school`)은 스코프 판정 대상이 아니다
        alias = colid.getText().strip('"').lower()
        if alias in outer or alias in seen or alias not in inner:
            continue
        seen.add(alias)
        out.append(UnresolvedAlias(alias, tuple(sorted(outer))))
    return out
