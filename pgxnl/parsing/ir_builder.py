"""ANTLR ParseTree -> QueryIR 추출 (docs/pgxnl_antlr_pipeline_design.md §2.2).

설계 문서는 별도 `parse_sql()`로 새로 파싱하는 스켈레톤을 제시했지만, 여기서는
ParsedStatement.raw_tree(이미 파싱된 트리)를 재사용한다 — 같은 SQL을 두 번 파싱하는
비용을 없애고, grammar 진입점이 AntlrPostgresParser 하나로 유지된다.

v1 범위: 최상위 SELECT 한 개의 절. 서브쿼리/집합연산은 분해하지 않고 QueryIR의
has_subquery / set_operation 플래그로만 표시한다(§7 1단계).
"""
from __future__ import annotations

from antlr4 import ParserRuleContext
from antlr4.tree.Tree import TerminalNode

from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
from pgxnl.parsing.ir import JoinNode, PredicateNode, QueryIR, SelectItem, normalize_expr

# 불리언 캐스케이드: grammar가 우선순위별로 규칙을 쪼개 두었다(a_expr_or -> a_expr_and
# -> a_expr_between -> ... -> a_expr_compare). AND/OR 트리를 만들 때 이 구조를 그대로 탄다.
_OR_CTX = _P.A_expr_orContext
_AND_CTX = _P.A_expr_andContext
_NOT_CTX = _P.A_expr_unary_notContext
_CMP_CTX = _P.A_expr_compareContext

# 서브쿼리 경계 — 최상위 절을 훑을 때 이 안쪽으로는 들어가지 않는다.
_SUBQUERY_CTX = (_P.Select_with_parensContext,)

_COMPARATORS = {
    "EQUAL": "=", "NOT_EQUALS": "!=", "LT": "<", "GT": ">",
    "LESS_EQUALS": "<=", "GREATER_EQUALS": ">=",
}


def _text(sql: str, ctx: ParserRuleContext) -> str:
    """원본 입력에서 문자 구간을 그대로 슬라이스한다.

    ctx.getText()는 토큰을 공백 없이 이어붙여 `countdistinctid`처럼 오염된다
    (postgresql_parser.enterJoin_qual에 같은 이유의 주석이 있다).
    """
    if ctx.start is None or ctx.stop is None:
        return ""
    return sql[ctx.start.start : ctx.stop.stop + 1]


def collect_contexts(node, cls, *, prune: tuple = ()) -> list:
    """전위 순회로 cls 인스턴스를 모은다. 찾으면 그 하위로는 더 내려가지 않고,
    prune 타입 서브트리는 아예 건너뛴다(서브쿼리 격리용)."""
    found: list = []

    def walk(n) -> None:
        if isinstance(n, cls):
            found.append(n)
            return
        if isinstance(n, (*prune, TerminalNode)):
            return
        for i in range(n.getChildCount()):
            walk(n.getChild(i))

    walk(node)
    return found


def _find_first(node, cls, *, prune: tuple = ()):
    hits = collect_contexts(node, cls, prune=prune)
    return hits[0] if hits else None


def _single(value):
    """ANTLR 접근자는 규칙이 좌재귀거나 반복이면 리스트를, 아니면 단일 ctx를 준다.
    같은 이름이 문맥에 따라 둘 다 나오므로 항상 하나로 정규화한다."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _first_present(ctx, *names: str):
    """주어진 접근자 이름들을 차례로 시도해 처음 채워진 것을 돌려준다."""
    for name in names:
        if not hasattr(ctx, name):
            continue
        found = _single(getattr(ctx, name)())
        if found is not None:
            return found
    return None


def _has_token(ctx, *names: str) -> bool:
    """ctx의 직계 자식 중 지정한 이름의 터미널 토큰이 있는지."""
    symbolic = _P.symbolicNames
    wanted = {n for n in names}
    for i in range(ctx.getChildCount()):
        child = ctx.getChild(i)
        if not isinstance(child, TerminalNode):
            continue
        idx = child.getSymbol().type
        if 0 <= idx < len(symbolic) and symbolic[idx] in wanted:
            return True
    return False


# --------------------------------------------------------------------------- 술어


def _build_predicate(sql: str, ctx) -> PredicateNode | None:
    """a_expr 계열 컨텍스트를 AND/OR/CMP 트리로 분해한다."""
    if ctx is None:
        return None

    if isinstance(ctx, _OR_CTX):
        operands = ctx.a_expr_and()
        if isinstance(operands, list) and len(operands) > 1:
            return PredicateNode(op="OR", children=_build_children(sql, operands))
    if isinstance(ctx, _AND_CTX):
        operands = ctx.a_expr_between()
        if isinstance(operands, list) and len(operands) > 1:
            return PredicateNode(op="AND", children=_build_children(sql, operands))
    if isinstance(ctx, _NOT_CTX) and _has_token(ctx, "NOT"):
        inner = _first_present(ctx, "a_expr_isnull", "a_expr_unary_not")
        if inner is not None:
            return PredicateNode(op="NOT", children=_build_children(sql, [inner]))
    if isinstance(ctx, _CMP_CTX):
        node = _build_comparison(sql, ctx)
        if node is not None:
            return node

    # 단일 자식만 있는 캐스케이드 단계는 그대로 통과시킨다.
    inner_ctxs = [
        ctx.getChild(i) for i in range(ctx.getChildCount()) if isinstance(ctx.getChild(i), ParserRuleContext)
    ]
    if len(inner_ctxs) == 1 and not _is_leafish(ctx):
        return _build_predicate(sql, inner_ctxs[0])

    return PredicateNode(op="RAW", left=normalize_expr(_text(sql, ctx)))


def _build_children(sql: str, operands: list) -> list[PredicateNode]:
    """자식 술어들을 만들되 None은 버린다 — 빈 자식이 트리에 섞이면 signature()가
    비교 불가능한 형태가 된다."""
    built = (_build_predicate(sql, o) for o in operands)
    return [node for node in built if node is not None]


def _is_leafish(ctx) -> bool:
    """더 내려가도 불리언 구조가 나오지 않는 지점 — IN/LIKE/BETWEEN/IS NULL 등은
    v1에서 통째로 RAW 잎으로 둔다(설계 문서 §2.1의 'leaf는 비교 predicate')."""
    return isinstance(
        ctx,
        (
            _P.A_expr_inContext,
            _P.A_expr_likeContext,
            _P.A_expr_betweenContext,
            _P.A_expr_isnullContext,
            _P.A_expr_is_notContext,
        ),
    ) and ctx.getChildCount() > 1


def _build_comparison(sql: str, ctx) -> PredicateNode | None:
    symbolic = _P.symbolicNames
    comparator = None
    for i in range(ctx.getChildCount()):
        child = ctx.getChild(i)
        if isinstance(child, TerminalNode):
            idx = child.getSymbol().type
            name = symbolic[idx] if 0 <= idx < len(symbolic) else ""
            if name in _COMPARATORS:
                comparator = _COMPARATORS[name]
                break
    if comparator is None:
        return None
    operands = [
        ctx.getChild(i) for i in range(ctx.getChildCount()) if isinstance(ctx.getChild(i), ParserRuleContext)
    ]
    if len(operands) != 2:
        return None
    return PredicateNode(
        op="CMP",
        left=normalize_expr(_text(sql, operands[0])),
        comparator=comparator,
        right=normalize_expr(_text(sql, operands[1])),
    )


# --------------------------------------------------------------------------- 절


def _build_select_items(sql: str, target_list) -> list[SelectItem]:
    items: list[SelectItem] = []
    for el in collect_contexts(target_list, _P.Target_elContext, prune=_SUBQUERY_CTX):
        if isinstance(el, _P.Target_starContext):
            items.append(SelectItem(expr="*"))
            continue
        expr_ctx = el.a_expr() if hasattr(el, "a_expr") else None
        if expr_ctx is None:
            items.append(SelectItem(expr=normalize_expr(_text(sql, el))))
            continue
        alias_ctx = None
        if hasattr(el, "colLabel") and el.colLabel() is not None:
            alias_ctx = el.colLabel()
        elif hasattr(el, "bareColLabel") and el.bareColLabel() is not None:
            alias_ctx = el.bareColLabel()
        items.append(
            SelectItem(
                expr=normalize_expr(_text(sql, expr_ctx)),
                alias=normalize_expr(_text(sql, alias_ctx)) if alias_ctx is not None else None,
            )
        )
    return items


def _token_name(node: TerminalNode) -> str:
    idx = node.getSymbol().type
    symbolic = _P.symbolicNames
    return symbolic[idx] if 0 <= idx < len(symbolic) else ""


def _join_type_name(join_type_ctx) -> str:
    for kind in ("LEFT", "RIGHT", "FULL", "INNER_P"):
        if _has_token(join_type_ctx, kind):
            return "INNER" if kind == "INNER_P" else kind
    return "INNER"


def _relation_name(sql: str, table_ref) -> str:
    rel = _first_present(table_ref, "relation_expr")
    if rel is not None:
        return normalize_expr(_text(sql, rel))
    sub = _find_first(table_ref, _P.Select_with_parensContext)
    return "(subquery)" if sub is not None else normalize_expr(_text(sql, table_ref))


def _build_from(sql: str, from_clause) -> tuple[list[str], list[JoinNode]]:
    """FROM 절을 기본 테이블 목록과 JOIN 목록으로 나눈다."""
    tables: list[str] = []
    joins: list[JoinNode] = []
    if from_clause is None:
        return tables, joins
    from_list = _first_present(from_clause, "from_list")
    if from_list is None:
        return tables, joins
    for ref in collect_contexts(from_list, _P.Table_refContext, prune=_SUBQUERY_CTX):
        _split_table_ref(sql, ref, tables, joins)
    return tables, joins


def _split_table_ref(sql: str, ref, tables: list[str], joins: list[JoinNode]) -> None:
    """table_ref 하나를 기본 테이블과 JOIN들로 분해한다.

    ANTLR이 좌재귀를 평탄화하기 때문에 트리가 중첩이 아니라 자식 시퀀스로 나온다:
        relation_expr alias_clause JOIN table_ref join_qual (join_type)? JOIN table_ref join_qual ...
    따라서 자식을 순서대로 훑으면서 JOIN 토큰을 경계로 끊어야 한다. 중첩 구조로
    가정하고 좌측을 재귀하면 기본 테이블과 ON 조건이 서로 어긋나게 붙는다(실측).
    """
    pending_type: str | None = None
    awaiting_table = False
    current: JoinNode | None = None
    base_captured = False

    for i in range(ref.getChildCount()):
        child = ref.getChild(i)

        if isinstance(child, TerminalNode):
            name = _token_name(child)
            if name in ("CROSS", "NATURAL"):
                pending_type = name
            elif name == "JOIN":
                awaiting_table = True
            continue

        if isinstance(child, _P.Join_typeContext):
            pending_type = _join_type_name(child)
            continue

        if isinstance(child, _P.Join_qualContext):
            if current is not None:
                _apply_join_qual(sql, child, current)
            continue

        if isinstance(child, _P.Table_refContext):
            if awaiting_table:
                current = JoinNode(
                    table=_relation_name(sql, child), join_type=pending_type or "INNER"
                )
                joins.append(current)
                pending_type, awaiting_table = None, False
            elif not base_captured:
                tables.append(_relation_name(sql, child))
                base_captured = True
            continue

        if not base_captured and isinstance(child, _P.Relation_exprContext):
            tables.append(normalize_expr(_text(sql, child)))
            base_captured = True
        elif not base_captured and isinstance(child, _P.Select_with_parensContext):
            tables.append("(subquery)")
            base_captured = True


def _apply_join_qual(sql: str, qual, node: JoinNode) -> None:
    on_expr = _first_present(qual, "a_expr")
    if on_expr is not None:
        node.on = _build_predicate(sql, on_expr)
        return
    name_list = _first_present(qual, "name_list")
    if name_list is not None:
        node.using = [normalize_expr(part) for part in _text(sql, name_list).split(",")]


def _build_order_by(sql: str, sort_clause) -> list[tuple[str, str]]:
    if sort_clause is None:
        return []
    out: list[tuple[str, str]] = []
    for sb in collect_contexts(sort_clause, _P.SortbyContext, prune=_SUBQUERY_CTX):
        expr_ctx = _first_present(sb, "a_expr")
        expr = normalize_expr(_text(sql, expr_ctx)) if expr_ctx is not None else ""
        asc_desc = _first_present(sb, "asc_desc_", "asc_desc")
        direction = "DESC" if asc_desc is not None and _has_token(asc_desc, "DESC") else "ASC"
        out.append((expr, direction))
    return out


def _int_or_none(text: str) -> int | None:
    text = text.strip()
    return int(text) if text.isdigit() else None


def _build_limit_offset(sql: str, select_limit) -> tuple[int | None, int | None]:
    if select_limit is None:
        return None, None
    limit = offset = None
    lc = _first_present(select_limit, "limit_clause")
    lv = _first_present(lc, "select_limit_value") if lc is not None else None
    if lv is not None:
        limit = _int_or_none(_text(sql, lv))
    oc = _first_present(select_limit, "offset_clause")
    ov = _first_present(oc, "select_offset_value") if oc is not None else None
    if ov is not None:
        offset = _int_or_none(_text(sql, ov))
    return limit, offset


# --------------------------------------------------------------------------- 진입점


def build_query_ir(sql: str, tree) -> QueryIR | None:
    """파싱된 트리에서 최상위 SELECT의 QueryIR을 만든다. SELECT가 아니면 None."""
    stmt = _find_first(tree, _P.SelectstmtContext)
    if stmt is None:
        return None

    no_parens = _find_first(stmt, _P.Select_no_parensContext)
    scope = no_parens if no_parens is not None else stmt

    # with_clause(CTE) 안의 SELECT를 최상위로 오인하면 안 된다 — select_clause에서만 찾는다.
    select_clause = _first_present(no_parens, "select_clause") if no_parens is not None else None
    search_root = select_clause if select_clause is not None else scope
    primary = _find_first(search_root, _P.Simple_select_pramaryContext)
    if primary is None:
        return None

    ir = QueryIR()

    for name in ("UNION", "INTERSECT", "EXCEPT"):
        if _collect_token_present(search_root, name):
            ir.set_operation = name
            break

    # grammar는 SELECT의 대상 목록을 opt_target_list(=target_list_)로 감싼다 —
    # target_list()는 TABLE 형태 등 다른 분기에서만 채워지므로 둘 다 본다.
    target_list = _first_present(primary, "target_list_", "target_list")
    if target_list is not None:
        ir.select_items = _build_select_items(sql, target_list)
    ir.distinct = _first_present(primary, "distinct_clause") is not None

    from_clause = _first_present(primary, "from_clause")
    ir.from_tables, ir.joins = _build_from(sql, from_clause)

    where_clause = _first_present(primary, "where_clause")
    where_expr = _first_present(where_clause, "a_expr") if where_clause is not None else None
    if where_expr is not None:
        ir.where = _build_predicate(sql, where_expr)

    group_clause = _first_present(primary, "group_clause")
    if group_clause is not None:
        ir.group_by = [
            normalize_expr(_text(sql, item))
            for item in collect_contexts(group_clause, _P.Group_by_itemContext, prune=_SUBQUERY_CTX)
        ]

    having_clause = _first_present(primary, "having_clause")
    having_expr = _first_present(having_clause, "a_expr") if having_clause is not None else None
    if having_expr is not None:
        ir.having = _build_predicate(sql, having_expr)

    if no_parens is not None:
        ir.order_by = _build_order_by(sql, _first_present(no_parens, "sort_clause_", "sort_clause"))
        ir.limit, ir.offset = _build_limit_offset(
            sql, _first_present(no_parens, "select_limit", "select_limit_")
        )

    # 최상위 절 어디든 서브쿼리가 있으면 구조 비교 신뢰도를 낮춘다.
    ir.has_subquery = _find_first(primary, _P.Select_with_parensContext) is not None

    return ir


def _collect_token_present(node, name: str) -> bool:
    symbolic = _P.symbolicNames
    target = next((i for i, s in enumerate(symbolic) if s == name), None)
    if target is None:
        return False

    def walk(n) -> bool:
        if isinstance(n, TerminalNode):
            return n.getSymbol().type == target
        if isinstance(n, _SUBQUERY_CTX):
            return False
        return any(walk(n.getChild(i)) for i in range(n.getChildCount()))

    return walk(node)
