"""참조한 컬럼이 그 테이블에 없는 경우 (§question_guard 7).

BIRD 459 실측: 모델이 `SELECT T1.street, T1.school FROM satscores AS T1 ...`을 냈다.
`street`·`school`은 `schools`에 있고 `satscores`에는 없다.

검증 계층이 이미 정확히 진단한다 — *"존재하지 않는 컬럼을 참조했습니다: t1.street
(satscores 테이블에 없음)"*. **그런데 그 판정은 ReAct 루프가 끝난 뒤라 모델이 못 본다.**

`AliasFixRule`은 이 경우를 못 고친다. 조건 3이 "그 컬럼을 가진 테이블에 이 질의가 쓴
별칭이 있다"인데, 459에는 `schools`가 아예 조인돼 있지 않다 — 조인을 새로 추가하는 것은
토큰 편집기의 범위를 넘는다. 그래서 **모델에게 넘긴다**: 어느 테이블에 있는지 알려주고
직접 조인하게 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MissingColumn:
    """참조된 `별칭.컬럼`이 그 테이블에 없을 때. `owners`는 그 컬럼을 가진 테이블들."""

    alias: str
    column: str
    table: str
    owners: tuple[str, ...]

    def message(self) -> str:
        if len(self.owners) == 1:
            one = self.owners[0]
            if "(" in one:  # 이미 조인돼 있고 별칭이 있다
                table, _, alias = one.partition("(")
                where = f"{table} 테이블에 있고 이미 {alias.rstrip(')')} 로 조인돼 있습니다 — 그 별칭을 쓰세요"
            else:
                where = f"{one} 테이블에 있습니다 — 그 테이블을 조인해서 쓰세요"
        elif self.owners:
            where = f"{', '.join(self.owners)} 테이블에 있습니다 — 질문에 맞는 쪽을 조인해서 쓰세요"
        else:
            where = "이 스키마의 어느 테이블에도 없습니다 — 컬럼 이름을 다시 확인하세요"
        return (
            f"SQL을 다시 작성하세요. {self.alias}.{self.column} 은(는) {self.table} 테이블에 "
            f"없어 실행하면 실패합니다. {self.column} 은(는) {where}."
        )


def _ancestors(node: Any):
    cur = getattr(node, "parentCtx", None)
    while cur is not None:
        yield cur
        cur = getattr(cur, "parentCtx", None)


def find_missing_columns(
    stmt: Any, *, columns_by_table: dict[str, set[str]], owners: dict[str, set[str]],
) -> list[MissingColumn]:
    """참조한 컬럼이 그 테이블에 없는 것들. 없으면 빈 리스트.

    `columns_by_table`은 이 질의에 참여한 테이블의 컬럼 집합(소문자), `owners`는
    `컬럼명 -> {소유 테이블}` 역인덱스다. 둘 다 이미 캐시된 값을 넘겨받는다 —
    이 함수는 조회를 하지 않는다.

    **서브쿼리 안의 참조도 본다.** 별칭을 스코프별로 풀기 때문이다 — 같은 서브쿼리 안의
    선언을 먼저 쓰고 없으면 바깥으로 떨어진다(상관 서브쿼리). 초판은 안쪽 참조를 통째로
    건너뛰었고, 그래서 BIRD 447이 `column t3."Enrollment (K-12)" does not exist` 로
    네 개 run 연속 죽었다 — 문제의 참조가 서브쿼리 안에 있었다.

    `aliases_in_query`를 주면 "그 컬럼을 가진 테이블이 이미 이 질의에 있다"를 알려줄 수
    있다 — 조인하라는 말보다 별칭을 짚어주는 편이 모델이 실행하기 쉽다(BIRD 447).
    """
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.ir_builder import collect_contexts

    if stmt is None or getattr(stmt, "raw_tree", None) is None:
        return []

    sub_spans = [
        (c.start.tokenIndex, c.stop.tokenIndex)
        for c in collect_contexts(stmt.raw_tree, _P.Select_with_parensContext)
    ]

    def _inside(idx: int) -> bool:
        return any(lo <= idx <= hi for lo, hi in sub_spans)

    # 별칭 선언을 **토큰 위치와 함께** 모은다. `stmt.alias_to_table`은 평면 dict라
    # 같은 별칭을 다른 테이블에 쓰는 스코프를 구분할 수 없다. `Relation_expr`에서
    # 부모 `Table_ref`를 거슬러 짝지으면 중첩 조인에서도 정확히 맞는다
    # (`collect_contexts`는 중첩 `Table_ref`로 내려가지 않으므로 그쪽은 못 쓴다).
    declarations: list[tuple[int, str, str]] = []   # (토큰 위치, 별칭, 테이블)
    for r in collect_contexts(stmt.raw_tree, _P.Relation_exprContext):
        qn = r.qualified_name() if hasattr(r, "qualified_name") else None
        if qn is None:
            continue
        table = qn.getText().rsplit(".", 1)[-1].strip('"').lower()
        holder = next(
            (a for a in _ancestors(r) if isinstance(a, _P.Table_refContext)), None,
        )
        clause = holder.alias_clause() if holder is not None and hasattr(holder, "alias_clause") else None
        colid_ctx = clause.colid() if clause is not None and hasattr(clause, "colid") else None
        alias = colid_ctx.getText().strip('"').lower() if colid_ctx is not None else table
        declarations.append((r.start.tokenIndex, alias, table))

    def _scope_for(idx: int) -> tuple[dict[str, str], dict[str, str]]:
        """이 위치에서 보이는 (별칭 -> 테이블, 테이블 -> 별칭).

        같은 서브쿼리 안의 선언을 먼저 쓰고, 없으면 바깥 선언으로 떨어진다(상관
        서브쿼리가 바깥 별칭을 참조하는 경우). 바깥 참조는 안쪽 선언을 보지 못한다.
        """
        span = next((s for s in sub_spans if s[0] <= idx <= s[1]), None)
        alias_map: dict[str, str] = {}
        # 바깥 선언부터 넣고 같은 스코프 선언으로 덮어쓴다 — 안쪽이 바깥을 가린다.
        for pos, alias, table in declarations:
            if not _inside(pos):
                alias_map[alias] = table
        if span is not None:
            for pos, alias, table in declarations:
                if span[0] <= pos <= span[1]:
                    alias_map[alias] = table
        return alias_map, {t: a for a, t in alias_map.items() if a != t}
    out: list[MissingColumn] = []
    seen: set[tuple[str, str]] = set()
    for ref in collect_contexts(stmt.raw_tree, _P.ColumnrefContext):
        colid, indirection = ref.colid(), ref.indirection()
        if colid is None or indirection is None:
            continue
        alias_to_table, table_alias = _scope_for(ref.start.tokenIndex)
        alias = colid.getText().strip('"').lower()
        raw = indirection.getText().lstrip(".")
        column = raw.strip('"').lower()
        table = alias_to_table.get(alias)
        if table is None or not column or "*" in column:
            continue  # 별칭을 모르거나 `t.*` 형태
        known = columns_by_table.get(table)
        if not known:
            continue  # 컬럼 목록이 없으면 판단 근거가 없다
        if column in known or (table, column) in seen:
            continue
        seen.add((table, column))
        owner_tables = sorted(owners.get(column, ()))
        joined = tuple(f"{t}({table_alias[t]})" if t in table_alias else t for t in owner_tables)
        out.append(MissingColumn(alias, raw.strip('"'), table, joined))
    return out
