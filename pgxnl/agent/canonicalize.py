"""SQL Canonicalization. design 문서 §5.8 참고.

결과는 동일하되 정해진 형태로 SQL을 강제 변환하는 규칙 기반 후처리. 캐시(§5.12)
저장 전에 반드시 거쳐야 캐시된 SQL의 형태가 일관되게 유지된다 — 이 순서(생성 →
Canonicalization → 캐시 저장)가 뒤바뀌면 캐시 히트마다 다른 스타일의 SQL이 섞인다.
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from pgxnl.governance.rules import Rule
from pgxnl.parsing.base import ParsedStatement, SqlParser, TokenEdit

logger = logging.getLogger(__name__)


class CanonRule(ABC):
    """개별 Canonicalization 규칙. AST를 순회해 위치를 찾고, 실제 텍스트 변경은
    TokenEdit 리스트로 반환해 TokenStreamRewriter가 적용하도록 한다 (§6 참고)."""

    #: 이 인스턴스를 만든 `pgxnl_rules.id`. `load_rules_from_store()`가 채운다.
    #: 어느 규칙이 실제로 편집을 냈는지 기록하기 위한 것 — 규칙을 뺄지 말지 판단하려면
    #: "지시했다"가 아니라 "일했다"를 세야 한다.
    source_rule_id: int | None = None

    def label(self) -> str:
        cls = type(self).__name__
        return f"{cls}(id {self.source_rule_id})" if self.source_rule_id else cls

    @abstractmethod
    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]: ...


class EnsureLimitRule(CanonRule):
    """LIMIT 없는 SELECT에 기본 LIMIT을 추가한다."""

    def __init__(self, default_limit: int = 1000) -> None:
        self._default_limit = default_limit

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.parsing.base import SqlKind

        if stmt.kind != SqlKind.SELECT:
            return []

        root = stmt.raw_tree
        stmts = root.stmtblock().stmtmulti().stmt()
        if len(stmts) != 1:
            return []
        top_stmt = stmts[0]

        select = top_stmt.selectstmt()
        if select is None:
            return []
        no_parens = select.select_no_parens()
        if no_parens is None:
            return []  # select_with_parens 형태는 안전하게 건너뛴다
        if no_parens.select_limit() is not None:
            return []  # 이미 LIMIT이 있음

        return [
            TokenEdit(
                kind="insert_after",
                start_token_index=top_stmt.stop.tokenIndex,
                text=f" LIMIT {self._default_limit}",
            )
        ]


class OrderByNullsRule(CanonRule):
    """ORDER BY에 NULL 정렬 위치를 명시한다.

    PostgreSQL 기본은 `ASC -> NULLS LAST`, `DESC -> NULLS FIRST`인데, SQLite는 NULL을
    가장 작은 값으로 보므로 `ASC -> NULLS FIRST`, `DESC -> NULLS LAST`가 된다. **정확히
    반대다.** BIRD gold SQL은 SQLite 원본을 PostgreSQL로 옮기면서 이 차이를 명시적
    NULLS 절로 보존했는데(`ORDER BY AvgScrMath DESC NULLS LAST`), 모델은 그 관례를
    몰라 그냥 `DESC`만 쓴다. 그러면 NULL 행이 1위로 올라와 top-N 질의가 통째로 틀린다
    — 실측상 오답의 47%(run 93/94에서 8/17건)가 이것 하나였다.

    mode:
      'nulls_last' (기본) ASC/DESC 모두 NULLS LAST를 **명시**한다. 원리는 하나 —
                   "NULL은 정렬 결과 맨 앞에 오지 않는다". ASC는 PostgreSQL 기본이 이미
                   NULLS LAST라 결과가 바뀌지 않지만, 명시해두면 (1) 의도가 SQL에 드러나고
                   (2) 기본값이 다른 DB로 옮겨도 같은 의미를 유지한다.
      'desc_last'  DESC에만 붙이고 ASC는 건드리지 않는다. PostgreSQL 전용으로는
                   'nulls_last'와 결과가 동일하다(ASC 기본이 NULLS LAST이므로).
      'sqlite'     ASC에는 NULLS FIRST, DESC에는 NULLS LAST를 붙여 SQLite 정렬을 재현한다.
                   **쓰지 말 것** — gold 패턴의 절반(NULLS FIRST)만 적용하고 그 짝인
                   NULL 필터를 빠뜨려 멀쩡한 질의를 망가뜨린다. "가장 낮은 점수"를 물었는데
                   점수가 NULL인 행을 반환하게 된다(ADR-0009의 seq 453 실측 참고).

    이미 NULLS 절이 있으면 건드리지 않는다 — 모델이 의도한 의미를 파괴하지 않기 위함.
    """

    _MODES = ("nulls_last", "desc_last", "sqlite")

    def __init__(self, mode: str = "nulls_last") -> None:
        if mode not in self._MODES:
            raise ValueError(f"알 수 없는 mode: {mode} (가능: {', '.join(self._MODES)})")
        self._mode = mode

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import collect_contexts

        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
            return []

        edits: list[TokenEdit] = []
        for sortby in collect_contexts(stmt.raw_tree, _P.SortbyContext):
            if _sortby_has_nulls_clause(sortby):
                continue
            if _sortby_is_desc(sortby, _P):
                suffix = " NULLS LAST"
            elif self._mode == "sqlite":
                suffix = " NULLS FIRST"
            elif self._mode == "nulls_last":
                suffix = " NULLS LAST"  # PostgreSQL 기본과 동일하지만 명시한다
            else:
                continue  # desc_last: ASC는 건드리지 않는다
            edits.append(
                TokenEdit(kind="insert_after", start_token_index=sortby.stop.tokenIndex, text=suffix)
            )
        return edits


def _sortby_has_nulls_clause(sortby) -> bool:
    for name in ("nulls_order_", "nulls_order"):
        if not hasattr(sortby, name):
            continue
        value = getattr(sortby, name)()
        if isinstance(value, list):
            if value:
                return True
        elif value is not None:
            return True
    return False


def _sortby_is_desc(sortby, parser_cls) -> bool:
    """ASC/DESC 표기가 없으면 PostgreSQL 기본인 ASC로 본다."""
    for name in ("asc_desc_", "asc_desc"):
        if not hasattr(sortby, name):
            continue
        value = getattr(sortby, name)()
        value = value[0] if isinstance(value, list) and value else value
        if value is None:
            continue
        return "DESC" in value.getText().upper()
    return False


class OrderByTiebreakRule(CanonRule):
    """`ORDER BY … LIMIT n` 에 결과의 단순 컬럼을 동점 기준으로 덧붙인다(2026-10-27, northwind 전용으로 시작).

    정렬 기준이 하나면 경계에서 동점인 행 중 어느 것이 잘릴지 정해지지 않는다 — 같은 질문에 Top 10 이
    매번 달라질 수 있다. 실측: Northwind v2 seq 19(판매 수량 10·11위 1057 동률), seq 32(5회 함께 주문된
    11쌍 중 3쌍만 들어감). gold 는 `ORDER BY total_quantity DESC, p.product_name` 처럼 결과의 이름 컬럼을
    오름차순으로 붙여 가른다.

    SELECT 의 **단순 컬럼 참조**(집계·식·서브쿼리 제외) 중 ORDER BY 에 없는 것을 SELECT 순서대로 붙인다.
    SELECT 에 있는 컬럼이라 GROUP BY·DISTINCT 와도 충돌하지 않는다. 바깥 쿼리만 보고, UNION 등은 건너뛴다.

    `NULLS LAST` 정규화(규칙 43)도 마지막 정렬 키 바로 뒤에 글자를 넣는다. 규칙들은 모두 원본 트리를 보고
    편집이 한꺼번에 적용되므로 같은 자리에 넣으면 순서가 섞인다 — 그래서 여기는 LIMIT 키워드 **앞**에 넣는다.
    """

    _PLAIN_COL = re.compile(r'^(?:("[^"]+"|[A-Za-z_][\w$]*)\.)?("[^"]+"|[A-Za-z_][\w$]*)$')

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import _first_present, collect_contexts

        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
            return []
        outer = next(iter(collect_contexts(stmt.raw_tree, _P.Select_no_parensContext)), None)
        if outer is None:
            return []
        sort = _first_present(outer, "sort_clause_", "sort_clause")
        limit = _first_present(outer, "select_limit_", "select_limit")
        if sort is None or limit is None or not limit.getText().lower().startswith("limit"):
            return []
        prims = collect_contexts(outer.select_clause(), _P.Simple_select_pramaryContext)
        if len(prims) != 1:          # UNION/INTERSECT/EXCEPT
            return []
        target_list = _first_present(prims[0], "target_list_", "target_list")
        if target_list is None:
            return []
        elements = collect_contexts(target_list, _P.Target_elContext)

        sort_keys = set()
        for sb in collect_contexts(sort, _P.SortbyContext):
            key = sb.a_expr().getText().lower() if sb.a_expr() is not None else ""
            if key.isdigit() and 0 < int(key) <= len(elements):   # ORDER BY 1 → SELECT 첫 항목
                el = elements[int(key) - 1]
                expr = el.a_expr() if hasattr(el, "a_expr") else None
                key = (expr.getText() if expr is not None else el.getText()).lower()
            sort_keys.add(key)
            sort_keys.add(key.rsplit(".", 1)[-1])

        extra: list[str] = []
        for el in elements:
            expr = el.a_expr() if hasattr(el, "a_expr") else None
            if expr is None:
                return []            # `*` — 무엇이 붙을지 모른다
            text = expr.getText()
            if not self._PLAIN_COL.match(text):
                continue
            alias_ctx = _first_present(el, "colLabel", "identifier", "bareColLabel")
            names = {text.lower(), text.lower().rsplit(".", 1)[-1]}
            if alias_ctx is not None:
                names.add(alias_ctx.getText().lower())
            if names & sort_keys:
                continue
            extra.append(text)
        if not extra:
            return []
        return [TokenEdit(kind="insert_before", start_token_index=limit.start.tokenIndex,
                          text=", " + ", ".join(extra) + " ")]


class AliasFixRule(CanonRule):
    """존재하지 않는 `별칭.컬럼` 참조를 그 컬럼을 실제로 가진 테이블의 별칭으로 고친다.

    실측(run 103): 오답 18건 중 3건이 `column t1.street does not exist` 류였고,
    PostgreSQL이 HINT로 `t2.street`라고 정답까지 알려주고 있었다. BIRD
    california_schools는 테이블 간에 이름이 겹치는 컬럼이 조인 키 `cdscode` 하나뿐이라
    (schools 49컬럼 / frpm 29 / satscores 11), 어느 테이블 것인지 **모호함 없이** 결정된다.

    교정 조건 — 셋 다 만족할 때만 고친다:
      1. 참조된 별칭이 가리키는 테이블에 그 컬럼이 **없다**
      2. 이 질의에 참여한 테이블 중 그 컬럼을 가진 것이 **정확히 하나**다
      3. 그 테이블에 이 질의가 쓴 별칭이 있다

    모호하면(둘 이상이 가지고 있으면) 손대지 않는다 — 잘못 고치면 조용히 다른 값을
    반환하게 되어 에러보다 나쁘다.
    """

    def __init__(self, column_owners: dict[str, set[str]]) -> None:
        # 컬럼명(정규화) -> 그 컬럼을 가진 테이블명(소문자) 집합
        self._owners = column_owners

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import collect_contexts

        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None or not stmt.alias_to_table:
            return []

        # 서브쿼리가 있으면 손대지 않는다. alias_to_table은 트리 전체에서 모은 것이라
        # 스코프를 구분하지 못한다 — 서브쿼리 안에만 있는 별칭을 바깥 참조에 붙이면
        # `invalid reference to FROM-clause entry`로 실행 자체가 실패한다(실측: run 104
        # seq 447). 스코프 분석을 제대로 하기 전까지는 보수적으로 건너뛴다.
        # CTE 도 같다 — `WITH cr AS (…) SELECT cr.company_name FROM cr` 의 cr 은 CTE 라 카탈로그에
        # 컬럼이 없어 "없는 컬럼"으로 보이고, 안쪽 customers 의 별칭 c 로 바꿔 실행을 망가뜨렸다
        # (Northwind v2 run 565·566 seq 27·33 — 모델 SQL 은 gold 와 일치했다).
        if collect_contexts(stmt.raw_tree, _P.Select_with_parensContext) \
                or collect_contexts(stmt.raw_tree, _P.Common_table_exprContext):
            return []

        alias_to_table = {a.lower(): _bare_table(t) for a, t in stmt.alias_to_table.items()}
        # 테이블 -> 이 질의가 실제로 쓴 별칭. 명시적 별칭(T1)이 테이블명 자체보다 우선한다.
        table_to_alias: dict[str, str] = {}
        for alias, table in alias_to_table.items():
            if alias == table and table in table_to_alias:
                continue
            if alias != table or table not in table_to_alias:
                table_to_alias.setdefault(table, alias)
                if alias != table:
                    table_to_alias[table] = alias
        participating = set(alias_to_table.values())

        edits: list[TokenEdit] = []
        for ref in collect_contexts(stmt.raw_tree, _P.ColumnrefContext):
            colid, indirection = ref.colid(), ref.indirection()
            if colid is None or indirection is None:
                continue
            alias = _normalize_ident(colid.getText())
            column = _normalize_ident(indirection.getText().lstrip("."))
            current_table = alias_to_table.get(alias)
            if current_table is None or column not in self._owners:
                continue  # 별칭을 모르거나(서브쿼리 등) 스키마에 없는 컬럼 — 손대지 않는다
            if current_table in self._owners[column]:
                continue  # 이미 올바른 참조
            candidates = self._owners[column] & participating
            if len(candidates) != 1:
                continue  # 후보가 없거나 모호함 — 잘못 고치면 조용한 오답이 된다
            target_alias = table_to_alias.get(next(iter(candidates)))
            if not target_alias or target_alias == alias:
                continue
            edits.append(
                TokenEdit(
                    kind="replace",
                    start_token_index=colid.start.tokenIndex,
                    end_token_index=colid.stop.tokenIndex,
                    text=target_alias,
                )
            )
        return edits


class CanonicalColumnRule(CanonRule):
    """같은 개념의 사본 컬럼 참조를 **정본 컬럼**으로 바꾼다.

    Design Lab이 찾아낸 "이 컬럼은 저 컬럼의 사본이고 값이 N% 어긋난다"를 실제 교정으로
    옮긴다(§Design Lab). `frpm."School Name"`과 `schools.school`은 같은 학교 이름인데
    9,941행 중 207행이 다르므로, **어느 쪽을 쓰느냐로 답이 갈린다.**

    같은 내용을 프롬프트로 세 번 시도해 세 번 실패했다(규칙 id=26 두 번, id=27 한 번):
    스키마에 `copy of schools.school` 표시를 넣고 "표시된 컬럼 대신 X를 쓰라"고 명시해도
    **목표 문항(seq 442)이 6회 모두 안 움직였다.** 결정론적 교정으로 옮긴다.

    교정 조건 — 넷 다 만족할 때만 고친다(`AliasFixRule`과 같은 원칙):

      1. 참조한 `별칭.컬럼`이 사본 목록에 있다
      2. **정본 테이블이 이 질의에 이미 조인돼 있다** — 조인을 새로 추가하지 않는다.
         정본이 없는 질의(BIRD seq 443의 gold가 그렇다)는 사본을 쓰는 게 맞다.
      3. 정본 테이블에 이 질의가 쓴 별칭이 있다
      4. 서브쿼리가 없다 — `alias_to_table`이 스코프를 구분하지 못한다
         (`AliasFixRule`이 이것 때문에 실행 자체를 실패시킨 적이 있다: run 104 seq 447)

    컬럼명까지 바꾸므로 잘못 고치면 **조용한 오답**이 된다 — 에러보다 나쁘다. 그래서
    조건이 하나라도 어긋나면 손대지 않는다.
    """

    def __init__(self, copies: dict[tuple[str, str], tuple[str, str]]) -> None:
        #: (사본테이블, 사본컬럼) -> (정본테이블, 정본컬럼). 전부 소문자로 정규화한다.
        self._copies = {
            (t.lower(), c.lower()): (ct.lower(), cc)
            for (t, c), (ct, cc) in copies.items()
        }

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import collect_contexts

        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None or not stmt.alias_to_table:
            return []
        if not self._copies:
            return []
        # 예전엔 서브쿼리가 하나라도 있으면 전부 포기했다("스코프를 구분할 수 없다").
        # 실제 위험은 서브쿼리 자체가 아니라 **한 별칭이 두 테이블에 묶이는 것**이다 —
        # 평면 dict라 안쪽이 바깥을 덮어써 바깥 컬럼을 엉뚱한 테이블로 오해한다. 파서가
        # 그 충돌을 `ambiguous_aliases`로 알려주므로 그 경우만 포기하면 된다.
        # 서브쿼리를 쓰면서 별칭이 겹치지 않는 질의(BIRD 447이 그렇다)는 안전하다.
        if stmt.ambiguous_aliases:
            return []
        # 파생 테이블(FROM 안의 서브쿼리)에 붙은 별칭은 **테이블 별칭이 아니다** —
        # 그 별칭의 컬럼은 서브쿼리가 이미 골라 놓은 것이라 정본 테이블의 컬럼으로
        # 바꿔치면 다른 값을 읽는다. 파서는 파생 별칭을 마지막으로 본 테이블에 묶으므로
        # (`(SELECT ... FROM frpm) x` -> `x: frpm`) 별칭 충돌로는 걸러지지 않는다.
        for ref in collect_contexts(stmt.raw_tree, _P.Table_refContext):
            if getattr(ref, "select_with_parens", None) and ref.select_with_parens() is not None:
                return []

        # **서브쿼리 안에서 선언된 별칭은 바깥에서 쓸 수 없다.** `alias_to_table`은 트리
        # 전체에서 모은 평면 dict라 안팎이 섞여 있다 — 그대로 쓰면 바깥 참조를 안쪽
        # 별칭으로 바꿔 실행이 죽는다. 실측(BIRD 447, 2026-09-10): `T1."School Name"`을
        # `t4.school`로 고쳤는데 t4는 스칼라 서브쿼리 안에만 있어
        # `missing FROM-clause entry for table "t4"`가 났다. 2026-09-09에 "서브쿼리가
        # 있으면 전부 포기"를 완화하면서 생긴 회귀다(별칭이 t1~t4로 전부 달라
        # `ambiguous_aliases`로는 안 걸린다).
        sub_spans = [
            (c.start.tokenIndex, c.stop.tokenIndex)
            for c in collect_contexts(stmt.raw_tree, _P.Select_with_parensContext)
        ]

        def _in_subquery(idx: int) -> bool:
            return any(lo <= idx <= hi for lo, hi in sub_spans)

        inner_aliases: set[str] = set()
        for a in collect_contexts(stmt.raw_tree, _P.Alias_clauseContext):
            colid_ctx = a.colid() if hasattr(a, "colid") else None
            if colid_ctx is not None and _in_subquery(a.start.tokenIndex):
                inner_aliases.add(_normalize_ident(colid_ctx.getText()))
        # 별칭 없이 쓴 테이블 이름도 그 자체가 참조 이름이 된다(`schools.school`).
        # 서브쿼리 안에만 있는 테이블을 바깥에서 그렇게 부르면 똑같이 실행이 죽는다.
        for r in collect_contexts(stmt.raw_tree, _P.Relation_exprContext):
            qn = r.qualified_name() if hasattr(r, "qualified_name") else None
            if qn is not None and _in_subquery(r.start.tokenIndex):
                inner_aliases.add(_normalize_ident(qn.getText().rsplit(".", 1)[-1]))

        alias_to_table = {a.lower(): _bare_table(t) for a, t in stmt.alias_to_table.items()}
        # 테이블 -> 이 질의가 쓴 별칭. 파서가 별칭을 소문자로 저장하므로 결과도
        # 소문자가 된다(`T2` -> `t2`) — PostgreSQL은 인용 없는 식별자를 소문자로
        # 접으므로 동작은 같고, `AliasFixRule`도 같게 동작한다.
        table_to_alias: dict[str, str] = {}
        for alias, table in alias_to_table.items():
            if alias in inner_aliases:
                continue  # 서브쿼리 전용 별칭 — 바깥 참조의 대체로 쓰면 안 된다
            if alias != table or table not in table_to_alias:
                table_to_alias.setdefault(table, alias)
                if alias != table:
                    table_to_alias[table] = alias

        edits: list[TokenEdit] = []
        for ref in collect_contexts(stmt.raw_tree, _P.ColumnrefContext):
            colid, indirection = ref.colid(), ref.indirection()
            if colid is None or indirection is None:
                continue
            if _in_subquery(ref.start.tokenIndex):
                continue  # 안쪽 참조는 안쪽 스코프로 판단해야 한다 — 지금은 손대지 않는다
            alias = _normalize_ident(colid.getText())
            column = _normalize_ident(indirection.getText().lstrip("."))
            table = alias_to_table.get(alias)
            if table is None:
                continue
            target = self._copies.get((table, column))
            if target is None:
                continue
            canon_table, canon_column = target
            canon_alias = table_to_alias.get(canon_table)
            if not canon_alias:
                continue  # 정본 테이블이 이 질의에 없다 — 조인을 추가하지 않는다
            edits.append(TokenEdit(
                kind="replace",
                start_token_index=colid.start.tokenIndex,
                end_token_index=ref.stop.tokenIndex,
                text=f"{canon_alias}.{_quote_ident(canon_column)}",
            ))
        return edits


def _quote_ident(name: str) -> str:
    """대문자나 공백이 있으면 큰따옴표로 감싼다 — `"School Name"` 같은 컬럼이 흔하다."""
    return name if name.islower() and name.replace("_", "").isalnum() else f'"{name}"'


def _bare_table(qualified: str) -> str:
    """'schema.table' -> 'table'."""
    return qualified.rsplit(".", 1)[-1].lower()


def _normalize_ident(text: str) -> str:
    """큰따옴표를 벗기고 소문자화 — PostgreSQL은 인용 없는 식별자를 소문자로 접는다."""
    return text.strip().strip('"').lower()


def build_column_owners(tables: list) -> dict[str, set[str]]:
    """TableMeta 리스트에서 `컬럼명 -> {소유 테이블}` 역인덱스를 만든다."""
    owners: dict[str, set[str]] = {}
    for t in tables:
        for c in t.columns:
            owners.setdefault(_normalize_ident(c.name), set()).add(t.name.lower())
    return owners


class DedupeColumnsRule(CanonRule):
    """SELECT 목록에 **완전히 같은 식**이 두 번 이상 있으면 마지막 하나만 남긴다.

    실측 BIRD 465: 질문이 세 가지를 한꺼번에 묻자("how many offers Multiple Provision
    Types?" + "List the number of cities" + "how many schools for each city") 모델이
    셋을 각각 컬럼으로 만들었는데, 그중 둘이 글자 그대로 같은 식이었다.

    ```sql
    SELECT COUNT(*) AS count, T1.city, COUNT(*) AS city_count ... GROUP BY T1.city
           ^^^^^^^^                    ^^^^^^^^  별칭만 다르고 같은 값
    ```

    GROUP BY가 걸려 있어 두 `COUNT(*)`는 **같은 값**이다. 정보가 늘지 않는데 컬럼만
    하나 더 붙어, 평가의 튜플 비교에서 어긋난다.

    **뒤에 나온 것을 남긴다.** 앞의 중복은 모델이 하위 질문 하나를 따로 답하려고 덧댄
    것이고, 표가 이미 그 답을 담고 있다. 실측(465)에서 앞을 지우면 `(city, count)`로
    gold와 일치하고, 뒤를 지우면 `(count, city)`가 되어 순서가 어긋난다 — 결과 비교가
    튜플 위치를 보기 때문이다(`_results_equal`).

    별칭은 비교에서 무시한다 — `COUNT(*) AS count`와 `COUNT(*) AS city_count`는 같은
    식이다. 반대로 식이 조금이라도 다르면(`COUNT(*)` vs `COUNT(T1.id)`) 손대지 않는다.

    영향 범위 측정(run 301, 30문항): 중복 컬럼이 있는 pred는 465 하나뿐이고 gold에는
    한 건도 없다. `column_order`와 같은 이유로 서브쿼리가 있으면 건너뛴다.
    """

    @staticmethod
    def _key(el: Any, sql: str) -> str:
        """별칭을 뺀 식 자체. 파스 트리에서 꺼내므로 공백·대소문자에 흔들리지 않고
        문자열 리터럴(`'a b'`)은 토큰 하나라 안쪽 공백이 보존된다 — 원문을 정규식으로
        다듬는 방식은 `COUNT( * )`와 `COUNT(*)`를 다르게 봤다."""
        expr = el.a_expr() if hasattr(el, "a_expr") else None
        return (expr.getText() if expr is not None else el.getText()).lower()

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import _first_present, collect_contexts

        sql = stmt.source_sql or ""
        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None or not sql:
            return []
        # 어느 SELECT의 목록인지 구분이 필요해지므로 서브쿼리가 있으면 건너뛴다.
        if collect_contexts(stmt.raw_tree, _P.Select_with_parensContext):
            return []

        primary = next(iter(collect_contexts(stmt.raw_tree, _P.Simple_select_pramaryContext)), None)
        if primary is None:
            return []
        target_list = _first_present(primary, "target_list_", "target_list")
        if target_list is None:
            return []
        elements = collect_contexts(target_list, _P.Target_elContext)
        if len(elements) < 2:
            return []

        keys = [self._key(el, sql) for el in elements]

        edits: list[TokenEdit] = []
        for idx, key in enumerate(keys):
            if idx == len(elements) - 1 or key not in keys[idx + 1 :]:
                continue  # 마지막 등장은 남긴다
            # 이 요소와 뒤따르는 쉼표까지 지운다 — 다음 요소 시작 직전까지.
            edits.append(TokenEdit(
                kind="delete",
                start_token_index=elements[idx].start.tokenIndex,
                end_token_index=elements[idx + 1].start.tokenIndex - 1,
            ))
        return edits


class ColumnOrderRule(CanonRule):
    """SELECT 절의 컬럼을 **질문에 언급된 순서**로 재배열한다.

    평가의 결과 비교가 튜플 위치를 보므로, 값이 같아도 순서가 다르면 오답이다
    (실측 seq 450: 질문은 `"Street, City, Zip and State"` 인데 모델이
    `street, city, state, zip` 순으로 냈다). 프롬프트 규칙 id=22가 같은 내용을
    지시하지만 지켜지지 않는 것이 확인됐다 — ADR-0009의 "판정 가능한 것은 코드로".

    **질문에 이름이 그대로 등장하는 컬럼만** 재배열 대상이다. 그 컬럼들끼리만 자리를
    맞바꾸고, 집계식이나 질문에 없는 컬럼은 원래 위치에 그대로 둔다 — 근거 없이
    움직이면 조용히 다른 결과를 만든다.

    **질문과 evidence가 서로 다른 순서를 말하면 아무것도 하지 않는다.** 실측(seq 450):
    질문은 `"Street, City, Zip and State"`, evidence는
    `"complete address has Street, City, State, Zip code"` 로 순서가 다르고 gold는
    evidence를 따랐다. 어느 쪽이 옳은지 코드가 판단할 수 없으므로 손대지 않는다 —
    초판은 질문만 보고 재배열해 오히려 정답이던 순서를 깨뜨렸다.
    """

    def __init__(
        self, question: str, evidence: str | None = None, on_conflict: str = "skip",
    ) -> None:
        self._question = question or ""
        self._evidence = evidence or ""
        # 'skip'(기본) | 'evidence' | 'question' — 아래 _conflicts_with_evidence 참고.
        self._on_conflict = on_conflict if on_conflict in ("skip", "evidence", "question") else "skip"

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.agent.question_guard import _plain_column_name
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir import normalize_expr
        from pgxnl.parsing.ir_builder import _first_present, collect_contexts

        sql = stmt.source_sql or ""
        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None or not sql or not self._question:
            return []
        # 서브쿼리가 있으면 어느 SELECT의 목록인지 구분이 필요해 보수적으로 건너뛴다.
        if collect_contexts(stmt.raw_tree, _P.Select_with_parensContext):
            return []

        primary = next(iter(collect_contexts(stmt.raw_tree, _P.Simple_select_pramaryContext)), None)
        if primary is None:
            return []
        target_list = _first_present(primary, "target_list_", "target_list")
        if target_list is None:
            return []
        elements = collect_contexts(target_list, _P.Target_elContext)
        if len(elements) < 2:
            return []

        lowered = self._question.lower()
        # (원래 위치, 토큰 구간, 원문, 질문 내 등장 위치, 컬럼명)
        movable: list[tuple[int, Any, str, int, str]] = []
        for idx, el in enumerate(elements):
            expr_ctx = el.a_expr() if hasattr(el, "a_expr") else None
            if expr_ctx is None:
                continue
            name = _plain_column_name(normalize_expr(sql[expr_ctx.start.start : expr_ctx.stop.stop + 1]))
            if not name:
                continue
            m = re.search(rf"\b{re.escape(name)}\b", lowered)
            if m is None:
                continue  # 질문에 없는 컬럼 — 옮길 근거가 없다
            movable.append((idx, el, sql[el.start.start : el.stop.stop + 1], m.start(), name))

        if len(movable) < 2:
            return []
        desired = sorted(movable, key=lambda x: x[3])
        evidence_order = self._evidence_order([x[4] for x in movable])
        if evidence_order is not None and evidence_order != [x[4] for x in desired]:
            # 질문과 evidence가 서로 다른 순서를 말한다 — 어느 쪽을 따를지는 정책이다.
            if self._on_conflict == "skip":
                return []
            if self._on_conflict == "evidence":
                rank = {name: i for i, name in enumerate(evidence_order)}
                desired = sorted(movable, key=lambda x: rank[x[4]])
            # 'question'이면 desired(질문 순서)를 그대로 쓴다
        if [x[0] for x in desired] == [x[0] for x in movable]:
            return []  # 이미 원하는 순서다

        return [
            TokenEdit(
                kind="replace",
                start_token_index=slot[1].start.tokenIndex,
                end_token_index=slot[1].stop.tokenIndex,
                text=wanted[2],
            )
            for slot, wanted in zip(movable, desired, strict=True)
            if slot[0] != wanted[0]
        ]

    def _evidence_order(self, names: list[str]) -> list[str] | None:
        """evidence가 이 컬럼들을 모두 언급하면 그 등장 순서를, 아니면 None.

        None은 "evidence가 순서에 대해 아무 말도 하지 않는다"는 뜻이라 질문 순서를 쓴다.

        **기본값이 'skip'인 이유** — 500문항 전수 측정(2026-09-07): 질문과 evidence가
        같은 컬럼들을 다른 순서로 말하는 문항은 **2건뿐이고 gold가 따른 쪽이 반반이다.**

            seq 450  evidence "complete address has Street, City, State, Zip code"
                     -> gold는 evidence를 따랐다 (구성 요소 나열이라 순서에 의미가 있다)
            seq 394  evidence "play format refers to format; cards name refers to name"
                     -> gold는 질문을 따랐다 (용어 사전이라 나열 순서는 우연이다)

        두 evidence는 성격이 다르지만(구성 나열 vs 용어 사전), 표본 2건으로 그 구분을
        코드에 넣는 것은 과적합이다. 충돌이 드물고 드물 때 손을 떼는 비용이 0이므로
        기본은 보수적으로 간다. 다른 정책이 낫다고 판단되면 규칙 정의에서
        `{"kind": "column_order", "on_conflict": "evidence"}`로 켜서 측정할 수 있다.
        """
        if not self._evidence:
            return None
        lowered = self._evidence.lower()
        positions: list[tuple[str, int]] = []
        for name in names:
            m = re.search(rf"\b{re.escape(name)}\b", lowered)
            if m is None:
                return None  # evidence가 이 컬럼들을 다 다루지 않는다
            positions.append((name, m.start()))
        return [n for n, _ in sorted(positions, key=lambda x: x[1])]


class DistinctSingleColumnRule(CanonRule):
    """GROUP BY 가 없는 문장에서 **단일 컬럼**을 조회하면 `SELECT DISTINCT` 로 바꾼다.

    사용자 결정(2026-10-06, BIRD card_games 전용으로 등록). 근거: card_games gold 는 값 목록을
    물을 때 DISTINCT 를 쓰는데(seq 349 "state its legalities status" → 3행) 모델은 3,810행을 냈다.
    pgxnl 채점(`_results_equal`)은 중복 개수까지 비교해 오답이 된다. (공식 BIRD 채점은 set 비교라
    이 규칙의 효과가 없다 — 그 점을 알고 card_games 에만 둔다.)

    건드리지 않는 경우 — 하나라도 해당하면 편집하지 않는다:
      - 바깥쪽 SELECT 가 아니거나(서브쿼리 안은 손대지 않는다) UNION 등 복합 쿼리
      - 이미 DISTINCT, GROUP BY/HAVING, `*`, 집계 함수(COUNT/SUM/AVG/MIN/MAX), 윈도 함수
      - **ORDER BY 에 SELECT 항목이 아닌 식이 있다** — PostgreSQL 은 `SELECT DISTINCT` 와
        그런 ORDER BY 를 함께 쓰면 오류를 낸다(시뮬레이션: card 377, california 453·456·464).
      - **조회 컬럼이 그 테이블의 PK(복합 PK 의 일부 포함)다**(사용자 지시 2026-10-06). PK 값은
        원래 행마다 고유하므로 중복이 보이면 조인 때문이고, 숨길 대상이 아니다. 별칭 없이
        컬럼명만 쓰고 테이블이 여럿이면, 참여 테이블 중 하나라도 그 이름이 PK 면 건너뛴다.
        `pk_columns` 를 못 받으면(카탈로그 없음) PK 판정 없이 적용한다.
    """

    def __init__(
        self, pk_columns: dict[str, set[str]] | None = None, only_columns: list[str] | None = None,
    ) -> None:
        #: 테이블(소문자, 스키마 없이) -> PK 컬럼(소문자) 집합
        self._pk = {t.lower(): {c.lower() for c in cols} for t, cols in (pk_columns or {}).items()}
        #: 정의의 `columns` — 주면 **이 이름의 컬럼만** 대상(별칭·테이블 접두 무시, 대소문자 무시).
        #: 사용자 지시(2026-10-06): card_games 에서 status·language·text 로 한정.
        self._only = {c.strip('"').lower() for c in only_columns} if only_columns else None

    def _is_pk(self, stmt: ParsedStatement, expr_key: str) -> bool:
        if not self._pk:
            return False
        col = expr_key.strip('"').lower()
        if "." in col:
            alias, col = col.rsplit(".", 1)
            alias = alias.strip('"')
            table = {a.lower(): _bare_table(t) for a, t in (stmt.alias_to_table or {}).items()}.get(alias, alias)
            return col.strip('"') in self._pk.get(_bare_table(table), set())
        tables = {_bare_table(t) for t in (stmt.referenced_tables or [])}
        return any(col in self._pk.get(t, set()) for t in tables)

    _AGG = re.compile(r"\b(count|sum|avg|min|max|string_agg|array_agg|bool_and|bool_or)\s*\(", re.I)

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import _first_present, collect_contexts

        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
            return []
        outer = next(iter(collect_contexts(stmt.raw_tree, _P.Select_no_parensContext)), None)
        if outer is None:
            return []
        prims = collect_contexts(outer.select_clause(), _P.Simple_select_pramaryContext)
        if len(prims) != 1:          # UNION/INTERSECT/EXCEPT
            return []
        primary = prims[0]
        if primary.distinct_clause() is not None or primary.group_clause() is not None \
                or primary.having_clause() is not None or primary.from_clause() is None:
            return []
        target_list = _first_present(primary, "target_list_", "target_list")
        if target_list is None:
            return []
        elements = collect_contexts(target_list, _P.Target_elContext)
        if len(elements) != 1:
            return []
        el = elements[0]
        text = el.getText()
        if text.endswith("*") or self._AGG.search(text) or "over(" in text.lower().replace(" ", ""):
            return []
        expr = el.a_expr() if hasattr(el, "a_expr") else None
        expr_key = (expr.getText() if expr is not None else text).lower()
        if self._is_pk(stmt, expr_key):
            return []
        if self._only is not None and expr_key.rsplit(".", 1)[-1].strip('"') not in self._only:
            return []
        alias_ctx = _first_present(el, "colLabel", "identifier", "bareColLabel")
        alias_key = alias_ctx.getText().lower() if alias_ctx is not None else None

        sort = _first_present(outer, "sort_clause_", "sort_clause")
        if sort is not None:
            for sb in collect_contexts(sort, _P.SortbyContext):
                key = sb.a_expr().getText().lower() if sb.a_expr() is not None else ""
                if key not in (expr_key, alias_key, "1"):
                    return []

        select_tok = primary.SELECT() if hasattr(primary, "SELECT") else None
        if select_tok is None:
            return []
        return [TokenEdit(kind="insert_after", start_token_index=select_tok.getSymbol().tokenIndex,
                          text=" DISTINCT")]


class DistinctWhenListAllRule(CanonRule):
    """질문이 "List all …" 이면 바깥 SELECT 에 DISTINCT 를 붙인다(2026-10-14 사용자 결정, card_games 전용).

    1:N 조인은 1쪽 행을 N쪽 수만큼 복제한다. SELECT 에 N쪽을 가르는 컬럼이 없으면 **똑같은 행**이
    반복되는데, 그건 정보가 아니다. 근거(BIRD 500 실측): "List all/every" 질문 16개 중 15개의 gold 가
    중복 없는 결과(10개는 DISTINCT·GROUP BY·IN 으로 명시, 5개는 구조상 없음). 예외 1개(qid 407
    "Lists all types…")는 gold 가 중복을 남긴다.

    **질문에 표지가 있을 때만** 편집한다 — 다른 질문은 SQL 도 프롬프트도 그대로다.
    건너뛰는 경우는 규칙 44(DistinctSingleColumnRule)와 같다: UNION 등 복합 쿼리, 이미 DISTINCT,
    GROUP BY/HAVING, FROM 없음, 집계·윈도 함수, ORDER BY 에 SELECT 항목이 아닌 식(PostgreSQL 오류).
    """

    #: "List all …" 뿐 아니라 "List the names of all …" 처럼 list 와 all/every 사이에 몇 낱말이 끼는 것도
    #: 포함한다(2026-10-14 사용자 요청으로 확장). 같은 절 안(마침표·물음표·세미콜론 전, 40자 이내)만 본다.
    #: BIRD 500: 넓힌 패턴 24문항 중 22개 gold 가 중복 없는 결과(기존 16개 중 15개).
    _LIST_ALL = re.compile(r"\blists?\b[^.?;]{0,40}?\b(?:all|every)\b", re.IGNORECASE)
    _AGG = DistinctSingleColumnRule._AGG

    def __init__(self, question: str) -> None:
        self._question = question or ""

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import _first_present, collect_contexts

        if not self._LIST_ALL.search(self._question):
            return []
        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
            return []
        outer = next(iter(collect_contexts(stmt.raw_tree, _P.Select_no_parensContext)), None)
        if outer is None:
            return []
        prims = collect_contexts(outer.select_clause(), _P.Simple_select_pramaryContext)
        if len(prims) != 1:
            return []
        primary = prims[0]
        if primary.distinct_clause() is not None or primary.group_clause() is not None \
                or primary.having_clause() is not None or primary.from_clause() is None:
            return []
        target_list = _first_present(primary, "target_list_", "target_list")
        if target_list is None:
            return []
        keys: set[str] = set()
        elements = collect_contexts(target_list, _P.Target_elContext)
        for i, el in enumerate(elements, 1):
            text = el.getText()
            if self._AGG.search(text) or "over(" in text.lower().replace(" ", ""):
                return []
            expr = el.a_expr() if hasattr(el, "a_expr") else None
            keys.add((expr.getText() if expr is not None else text).lower())
            alias_ctx = _first_present(el, "colLabel", "identifier", "bareColLabel")
            if alias_ctx is not None:
                keys.add(alias_ctx.getText().lower())
            keys.add(str(i))
        sort = _first_present(outer, "sort_clause_", "sort_clause")
        if sort is not None:
            for sb in collect_contexts(sort, _P.SortbyContext):
                key = sb.a_expr().getText().lower() if sb.a_expr() is not None else ""
                if key not in keys:
                    return []
        select_tok = primary.SELECT() if hasattr(primary, "SELECT") else None
        if select_tok is None:
            return []
        return [TokenEdit(kind="insert_after", start_token_index=select_tok.getSymbol().tokenIndex,
                          text=" DISTINCT")]


class YesNoUpperRule(CanonRule):
    """CASE 가 돌려주는 예/아니오 문자열을 대문자 `'YES'`/`'NO'` 로 맞춘다.

    사용자 결정(2026-10-07, BIRD 전용으로 등록). 근거: BIRD gold 는 예/아니오를 항상 대문자로
    쓴다(card_games 7회, student_club 1회 — 소문자·첫 글자 대문자는 0회). 모델은 `'Yes'`/`'No'` 를
    써서 공식 채점(set 비교, 정규화 없음)에서 틀린다 — card_games seq 382·379 가 대소문자만 달랐다.
    pgxnl 채점은 소문자로 비교해 이미 맞다고 본다.

    건드리는 곳은 **CASE 의 결과값(THEN/ELSE)뿐**이다 — WHERE 의 `= 'Yes'` 같은 비교값은 데이터와
    맞아야 하므로 손대지 않는다. 그 CASE 의 결과가 **전부** yes/no 문자열일 때만 고친다
    (`ELSE NULL`·다른 문자열이 섞이면 의미를 짐작하지 않고 그대로 둔다).
    """

    _YES_NO = re.compile(r"^'(yes|no)'$", re.I)

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P

        if stmt.raw_tree is None:
            return []
        edits: list[TokenEdit] = []
        # collect_contexts 는 매치한 노드 안으로 내려가지 않는다 — 중첩 CASE 까지 보려고 직접 순회한다.
        stack = [stmt.raw_tree]
        cases = []
        while stack:
            node = stack.pop()
            if isinstance(node, _P.Case_exprContext):
                cases.append(node)
            stack.extend(getattr(node, "children", None) or [])
        for case in cases:
            results = []
            wl = case.when_clause_list()
            for w in (wl.when_clause() if wl is not None else []):
                exprs = w.a_expr()
                if len(exprs) == 2:
                    results.append(exprs[1])
            default = case.case_default()
            if default is not None and default.a_expr() is not None:
                results.append(default.a_expr())
            if not results:
                continue
            literals = []
            for expr in results:
                if expr.start.tokenIndex != expr.stop.tokenIndex or not self._YES_NO.match(expr.getText()):
                    literals = None
                    break
                literals.append(expr.start)
            if not literals:
                continue
            for tok in literals:
                upper = tok.text.upper()
                if tok.text != upper:
                    edits.append(TokenEdit(kind="replace", start_token_index=tok.tokenIndex,
                                           end_token_index=tok.tokenIndex, text=upper))
        return edits


class SingleTableNoAliasRule(CanonRule):
    """테이블이 하나뿐인 조회에서 별칭을 뗀다: `SELECT T1.name FROM sets AS T1` -> `SELECT name FROM sets`.

    사용자 결정(2026-10-07, 전역). SQL 을 모르는 사용자가 읽는 SQL 이라 쓸모없는 별칭은 소음이다.
    프롬프트 규칙 13 에 "단일 테이블이면 붙이지 말라"를 넣어 봤지만 별칭이 5~6개 남았고, 문구 변경이
    무관한 문항을 흔들어 card_games +2 / california −2 로 갈렸다(run 380~383). 코드로는 프롬프트를
    건드리지 않아 다른 문항이 움직이지 않는다. 결과 행은 바뀌지 않는다(EX 불변).

    건드리지 않는 경우 — 하나라도 해당하면 편집하지 않는다:
      - SELECT 가 아니거나 문법 오류
      - 테이블 참조가 정확히 하나가 아니다(JOIN·쉼표 조인)
      - 서브쿼리·CTE·UNION 이 있다(상관 서브쿼리가 바깥 별칭을 쓸 수 있다)
      - 별칭이 없다
      - 별칭이 아닌 다른 한정자(`sets.name`, `schema.t.c`)는 그대로 둔다
    """

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind

        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None or not stmt.is_well_formed:
            return []
        if len(stmt.referenced_tables or []) != 1:
            return []

        nodes: dict[type, list] = {}

        def walk(n):
            nodes.setdefault(type(n), []).append(n)
            for ch in getattr(n, "children", None) or []:
                walk(ch)

        walk(stmt.raw_tree)
        if nodes.get(_P.Select_with_parensContext) or nodes.get(_P.With_clauseContext):
            return []
        if len(nodes.get(_P.Simple_select_pramaryContext, [])) != 1:
            return []
        if len(nodes.get(_P.Relation_exprContext, [])) != 1:
            return []
        aliases = nodes.get(_P.Alias_clauseContext, [])
        if len(aliases) != 1:
            return []
        alias_clause = aliases[0]
        colid = alias_clause.colid() if hasattr(alias_clause, "colid") else None
        has_col_list = hasattr(alias_clause, "name_list") and alias_clause.name_list() is not None
        if colid is None or has_col_list:
            return []  # 열 별칭 목록 `AS t(a, b)` 은 의미가 있어 손대지 않는다
        alias = colid.getText().strip('"').lower()

        tokens = stmt.raw_tree.parser.getTokenStream()
        start = alias_clause.start.tokenIndex
        # 앞 공백까지 지워 `sets  WHERE` 처럼 빈칸이 두 개 남지 않게 한다.
        if start > 0 and not tokens.get(start - 1).text.strip():
            start -= 1
        edits = [TokenEdit(kind="delete", start_token_index=start, end_token_index=alias_clause.stop.tokenIndex)]

        for ref in nodes.get(_P.ColumnrefContext, []):
            ind = ref.indirection() if hasattr(ref, "indirection") else None
            head = ref.colid() if hasattr(ref, "colid") else None
            if ind is None or head is None or head.getText().strip('"').lower() != alias:
                continue
            first = ind.indirection_el(0) if hasattr(ind, "indirection_el") else None
            if first is None or first.start.text != ".":
                continue
            # `T1` 과 뒤의 `.` 만 지운다 — 나머지(`name`, `"School Name"`, `*`)는 그대로.
            edits.append(TokenEdit(kind="delete", start_token_index=head.start.tokenIndex,
                                   end_token_index=first.start.tokenIndex))
        return edits


class SubqueryEqToInRule(CanonRule):
    """조건 위치의 `col = (SELECT …)` 를 `col IN (SELECT …)` 로 바꾼다.

    사용자 결정(2026-10-14, 전역). card_games seq 379: 모델이 `setcode = (SELECT setcode FROM cards WHERE
    name = …)` 를 써 서브쿼리가 여러 행을 돌려주자 실행 오류가 났다(run 422, 앞서 416). 같은 문항이 IN 으로
    쓰면 ✓✓(run 420). 실측(run 333 이후 pred 98건): `= (SELECT` 는 379·390·393 에서만 나왔고, 390(MAX)·393
    (LIMIT 1)은 늘 한 행이라 결과가 같다.

    조건 위치에서는 결과가 바뀌는 경우가 여러 행 오류뿐이다 — 한 행이면 같고, 0행이면 `=` 는 NULL, IN 은
    false 인데 WHERE·ON·HAVING·WHEN 에서는 둘 다 "통과 못 함"이다. 그래서 비교식에서 조건 절까지 올라가는
    길에 AND·OR·괄호만 있을 때 고친다. NOT·IS·함수·SELECT 목록 같은 다른 노드가 끼면 NULL 과 false 가
    갈릴 수 있어(`NOT (x = (…))` 는 0행일 때 NULL 대 true) 그대로 둔다. `<>` 등 다른 연산자도 그대로
    (`<> (…)` → NOT IN 은 NULL 의미가 다르다).
    """

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P

        if stmt.raw_tree is None:
            return []
        edits: list[TokenEdit] = []
        stack = [stmt.raw_tree]
        while stack:
            node = stack.pop()
            stack.extend(getattr(node, "children", None) or [])
            if not isinstance(node, _P.A_expr_compareContext) or node.getChildCount() != 3:
                continue
            op = node.getChild(1)
            if op.getText() != "=":
                continue
            sub = self._subquery(node.getChild(2), _P)
            if sub is None or self._limited(sub, _P):
                continue
            if self._in_condition(node, _P):
                tok = op.getSymbol()
                edits.append(TokenEdit(kind="replace", start_token_index=tok.tokenIndex,
                                       end_token_index=tok.tokenIndex, text="IN"))
        return edits

    @staticmethod
    def _subquery(expr, _P):
        # 한 자식씩 내려가 `( SELECT … )` 자체에 닿아야 한다 — `(SELECT …) + 1` 같은 식은 아니다.
        while not isinstance(expr, _P.Select_with_parensContext):
            ch = getattr(expr, "children", None)
            if not ch or len(ch) != 1:
                return None
            expr = ch[0]
        return expr

    @staticmethod
    def _limited(sub, _P) -> bool:
        """서브쿼리 자체에 LIMIT 이나 집계(MAX 등)가 있으면 True — 모델이 한 행을 의도해 쓴 모양이니 그대로
        둔다(사용자 지시, 2026-10-14). 안쪽에 또 중첩된 서브쿼리의 것은 보지 않는다."""
        from pgxnl.parsing.ir_builder import _first_present, collect_contexts

        body = next(iter(collect_contexts(sub, _P.Select_no_parensContext)), None)
        if body is None:
            return False
        for ch in body.children or []:
            if not isinstance(ch, _P.Select_clauseContext) and re.match(r"(limit|fetch)", ch.getText(), re.I):
                return True
        for prim in collect_contexts(body.select_clause(), _P.Simple_select_pramaryContext):
            target_list = _first_present(prim, "target_list_", "target_list")
            if target_list is not None and DistinctSingleColumnRule._AGG.search(target_list.getText()):
                return True
        return False

    @staticmethod
    def _in_condition(node, _P) -> bool:
        child, parent = node, node.parentCtx
        while parent is not None:
            if isinstance(parent, (_P.Where_clauseContext, _P.Having_clauseContext, _P.Join_qualContext)):
                return True
            if isinstance(parent, _P.When_clauseContext):
                exprs = parent.a_expr()
                return bool(exprs) and exprs[0] is child  # WHEN 의 조건 쪽만, THEN 결과는 아니다
            if isinstance(parent, (_P.A_expr_andContext, _P.A_expr_orContext)):
                pass
            elif isinstance(parent, _P.C_expr_exprContext) and parent.getChildCount() >= 3 \
                    and parent.getChild(0).getText() == "(" and parent.getChild(2).getText() == ")":
                pass  # `( 조건 )` 괄호
            elif parent.getChildCount() != 1:
                return False
            child, parent = parent, parent.parentCtx
        return False


class DatePartFuncRule(CanonRule):
    """`YEAR(x)`·`MONTH(x)`·`DAY(x)` 를 `EXTRACT(YEAR FROM x)` 꼴로 바꾼다.

    사용자 결정(2026-10-14, 전역). PostgreSQL 에는 이 함수들이 없어 실행 오류가 난다
    (`function year(timestamp with time zone) does not exist`). BIRD evidence 가 `YEAR(CreationDate)` 처럼
    MySQL·SQLite 식으로 써서 모델이 그대로 옮긴다 — codebase_community 330·336. 336 은 같은 설정에서
    run 마다 YEAR()/EXTRACT 로 갈렸다(435 ✓, 436 ✗, 437 ✓). 결과 값은 같다(EXTRACT 는 numeric 을 돌려주지만
    `= 2011`·`= '2011'` 비교 모두 성립).

    인자가 정확히 하나일 때만 바꾼다. 스키마 한정 이름(`myschema.year(x)`)은 사용자 함수일 수 있어 그대로 둔다.
    """

    _PARTS = {"year": "YEAR", "month": "MONTH", "day": "DAY"}

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P

        if stmt.raw_tree is None:
            return []
        edits: list[TokenEdit] = []
        stack = [stmt.raw_tree]
        while stack:
            node = stack.pop()
            stack.extend(getattr(node, "children", None) or [])
            if not isinstance(node, _P.Func_applicationContext) or node.getChildCount() != 4:
                continue
            name, lparen, args = node.getChild(0), node.getChild(1), node.getChild(2)
            part = self._PARTS.get(name.getText().lower())
            if part is None or lparen.getText() != "(" or not isinstance(args, _P.Func_arg_listContext):
                continue
            if any(getattr(ch, "getText", lambda: "")() == "," for ch in (args.children or [])):
                continue  # 인자 둘 이상 — 다른 함수다
            edits.append(TokenEdit(kind="replace", start_token_index=name.start.tokenIndex,
                                   end_token_index=lparen.getSymbol().tokenIndex, text=f"EXTRACT({part} FROM "))
        return edits


class DateLiteralCompareRule(CanonRule):
    """timestamp 컬럼을 날짜만 쓴 리터럴과 비교하면 컬럼을 `DATE(…)` 로 감싼다.

    사용자 결정(2026-10-14, codebase_community 전용). 날짜만 쓴 리터럴은 "그날"을 뜻하는데, timestamp 와
    그대로 비교하면 그 날 00:00:00 한 순간과 비교된다 — `> '2014-09-01'` 이 9/1 당일을 포함하고,
    `= '2014-09-01'` 은 사실상 0건이 된다. 실측: codebase_community 299, 질문 "after 2014/9/1", evidence
    `LastAccessDate > '2014-09-01'`, gold `DATE(LastAccessDate) > '2014-09-01'` — pred 5,148 대 gold 4,943
    (차이 205 는 9/1 당일 접속자).

    **timestamp 컬럼일 때만** 바꾼다(호출자가 `timestamp_columns` 로 알려 준다). date 컬럼은 결과가 같아
    손댈 이유가 없고, text 컬럼(student_club 등)은 `'2008-08-17 00:00:00' > '2008-08-17'` 같은 문자열 비교에
    기대는 gold 가 있어 바꾸면 깨진다. 리터럴에 시각이 붙어 있으면(`'2014-04-23 20:29:39'`) 그대로 둔다.
    """

    _DATE_ONLY = re.compile(r"^'\d{4}[-/]\d{1,2}[-/]\d{1,2}'$")
    _OPS = {"=", "<>", "!=", ">", "<", ">=", "<="}

    def __init__(self, timestamp_columns: dict[str, set[str]]):
        self._ts = {t.lower(): {c.lower() for c in cols} for t, cols in timestamp_columns.items()}

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P

        if stmt.raw_tree is None:
            return []
        aliases = {a.lower(): t.rsplit(".", 1)[-1].lower() for a, t in (stmt.alias_to_table or {}).items()}
        tables = [t.rsplit(".", 1)[-1].lower() for t in (stmt.referenced_tables or [])]
        edits: list[TokenEdit] = []
        stack = [stmt.raw_tree]
        while stack:
            node = stack.pop()
            stack.extend(getattr(node, "children", None) or [])
            col = None
            if isinstance(node, _P.A_expr_compareContext) and node.getChildCount() == 3:
                if node.getChild(1).getText() in self._OPS and self._is_date(node.getChild(2), _P):
                    col = self._descend(node.getChild(0), _P.ColumnrefContext)
            elif isinstance(node, _P.A_expr_betweenContext) and node.getChildCount() == 5:
                if node.getChild(1).getText().upper() == "BETWEEN" \
                        and self._is_date(node.getChild(2), _P) and self._is_date(node.getChild(4), _P):
                    col = self._descend(node.getChild(0), _P.ColumnrefContext)
            if col is None or not self._is_timestamp(col.getText(), aliases, tables):
                continue
            edits.append(TokenEdit(kind="insert_before", start_token_index=col.start.tokenIndex, text="DATE("))
            edits.append(TokenEdit(kind="insert_after", start_token_index=col.stop.tokenIndex, text=")"))
        return edits

    @staticmethod
    def _descend(node, cls):
        # 한 자식씩 내려가 그 노드 자체에 닿아야 한다 — `col + 1`·`DATE(col)` 같은 식은 아니다.
        while not isinstance(node, cls):
            ch = getattr(node, "children", None)
            if not ch or len(ch) != 1:
                return None
            node = ch[0]
        return node

    def _is_date(self, node, _P) -> bool:
        lit = self._descend(node, _P.SconstContext)
        return lit is not None and bool(self._DATE_ONLY.match(lit.getText()))

    def _is_timestamp(self, ref: str, aliases: dict[str, str], tables: list[str]) -> bool:
        parts = [p.strip('"').lower() for p in ref.split(".")]
        column = parts[-1]
        if len(parts) >= 2:
            table = aliases.get(parts[-2], parts[-2])
            return column in self._ts.get(table, set())
        # 한정자 없는 컬럼 — 조회한 테이블 중 그 이름이 timestamp 인 곳이 있으면.
        return any(column in self._ts.get(t, set()) for t in tables)


class CountGroupsRule(CanonRule):
    """"How many …" 질문에 그룹별 집계만 여러 행 내는 SQL 을 그룹 수 하나로 감싼다(2026-10-15 사용자, 전역).

    `SELECT COUNT(userid) FROM badges GROUP BY userid HAVING COUNT(name) > 5` → 사용자마다 한 행.
    질문은 그런 사용자가 몇 명인지 묻는다 → `SELECT COUNT(*) FROM (…) AS t`.
    과거 pred 10,027건 중 이 모양(바깥 SELECT 가 집계뿐 + GROUP BY)은 codebase_community 320 에서만 12번, 모두 오답.
    "each/per/every" 가 있으면 그룹별 답을 원하는 것이라 그대로 둔다.
    """

    _HOW_MANY = re.compile(r"\bhow many\b", re.I)
    _PER_GROUP = re.compile(r"\b(each|per|every)\b", re.I)
    _AGG = re.compile(r"^(count|sum|avg|min|max)\(", re.I)

    def __init__(self, question: str) -> None:
        self._question = question or ""

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.base import SqlKind
        from pgxnl.parsing.ir_builder import _first_present, collect_contexts

        q = self._question
        if not self._HOW_MANY.search(q) or self._PER_GROUP.search(q):
            return []
        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
            return []
        outer = next(iter(collect_contexts(stmt.raw_tree, _P.Select_no_parensContext)), None)
        if outer is None or _first_present(outer, "sort_clause_", "sort_clause") is not None:
            return []
        if any(ch.getText().lower().startswith(("limit", "fetch")) for ch in outer.children or []):
            return []
        prims = collect_contexts(outer.select_clause(), _P.Simple_select_pramaryContext)
        if len(prims) != 1 or prims[0].group_clause() is None:
            return []
        target_list = _first_present(prims[0], "target_list_", "target_list")
        items = collect_contexts(target_list, _P.Target_elContext) if target_list is not None else []
        if not items or not all(self._AGG.match(el.getText()) for el in items):
            return []
        return [
            TokenEdit(kind="insert_before", start_token_index=outer.start.tokenIndex, text="SELECT COUNT(*) FROM ("),
            TokenEdit(kind="insert_after", start_token_index=outer.stop.tokenIndex, text=") AS t"),
        ]


class RoundNumericRule(CanonRule):
    """`ROUND(식, n)` 의 식을 `(식)::numeric` 으로 감싼다.

    사용자 결정(2026-10-28, northwind 전용). PostgreSQL 에는 `round(double precision, integer)` 가 없어
    실행 오류가 난다. 프롬프트 규칙 #60("ROUND(CAST(값 AS NUMERIC), 자릿수)")이 있어도 모델이
    `ROUND(CAST(a AS NUMERIC) / b * 100, 2)` 처럼 캐스트 뒤에 double 과 다시 연산해 Northwind L4-04 가
    run 587·589 에서 실패했다. numeric 으로 바꿔 반올림하면 값은 같다. BIRD gold 는 REAL 결과를
    기대하므로([[bird_gold_uses_real]]) 전역으로 두지 않는다.

    인자가 정확히 둘일 때만, 첫 인자가 이미 `CAST(… AS NUMERIC)`·`…::numeric` 이면 그대로 둔다.
    """

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P

        if stmt.raw_tree is None:
            return []
        edits: list[TokenEdit] = []
        stack = [stmt.raw_tree]
        while stack:
            node = stack.pop()
            stack.extend(getattr(node, "children", None) or [])
            if not isinstance(node, _P.Func_applicationContext) or node.getChildCount() != 4:
                continue
            name, lparen, args = node.getChild(0), node.getChild(1), node.getChild(2)
            if name.getText().lower() != "round" or lparen.getText() != "(" \
                    or not isinstance(args, _P.Func_arg_listContext):
                continue
            kids = list(args.children or [])
            if len(kids) != 3 or kids[1].getText() != ",":
                continue
            first = kids[0]
            text = first.getText().lower()
            if re.fullmatch(r"cast\(.*asnumeric(\(\d+(,\d+)?\))?\)", text) or re.search(r"::numeric(\(\d+(,\d+)?\))?$", text):
                continue
            edits.append(TokenEdit(kind="insert_before", start_token_index=first.start.tokenIndex, text="("))
            edits.append(TokenEdit(kind="insert_after", start_token_index=first.stop.tokenIndex, text=")::numeric"))
        return edits


class CastFloatRule(CanonRule):
    """지정한 컬럼을 `CAST(… AS REAL)`·`…::real` 로 바꿀 때 REAL 대신 FLOAT(double precision)를 쓴다.

    사용자 결정(2026-10-19, debit_card_specializing 전용, columns=["consumption"]). evidence 가 "cast the
    consumption into float" 라고 지시하고 gold 도 float 인데, 생성 규칙 4("나눗셈 시 CAST(컬럼 AS REAL)")가
    이겨 모델이 REAL 을 쓴다(debit_card 3·13, run 512 부터). consumption 합계가 수천만이라 REAL(4바이트)로는
    자릿수가 잘려 값이 달라진다. 다른 BIRD 스키마 gold 는 REAL 이라([[bird_gold_uses_real]]) 전역으로 두지 않는다.
    캐스트 대상 식에 지정 컬럼이 들어 있을 때만 바꾼다.
    """

    def __init__(self, columns: list[str]):
        self._cols = [re.compile(rf"(?<![\w\"]){re.escape(c.lower())}(?![\w\"])") for c in columns]

    def collect_edits(self, stmt: ParsedStatement) -> list[TokenEdit]:
        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P

        if stmt.raw_tree is None or not self._cols:
            return []
        edits: list[TokenEdit] = []
        stack = [stmt.raw_tree]
        while stack:
            node = stack.pop()
            stack.extend(getattr(node, "children", None) or [])
            if not isinstance(node, _P.TypenameContext) or node.getText().lower() != "real":
                continue
            parent = node.parentCtx
            kids = list(getattr(parent, "children", None) or [])
            if isinstance(parent, _P.Func_expr_common_subexprContext) and len(kids) >= 5 \
                    and kids[0].getText().upper() == "CAST":
                operand = kids[2].getText()
            elif len(kids) == 3 and kids[1].getText() == "::":
                operand = kids[0].getText()
            else:
                continue
            if any(c.search(operand.lower()) for c in self._cols):
                edits.append(TokenEdit(kind="replace", start_token_index=node.start.tokenIndex,
                                       end_token_index=node.stop.tokenIndex, text="FLOAT"))
        return edits


def _scope_rank(r: Rule) -> int:
    """범위가 좁을수록 크다: 스키마 전용 2 > 대상 전용 1 > 전역 0."""
    if getattr(r, "schema_name", None):
        return 2
    return 1 if r.target_name is not None else 0


def _one_per_kind(rule_defs: list[Rule]) -> list[Rule]:
    """canonicalization 규칙을 종류(kind)마다 하나로 줄인다 — **좁은 범위가 우선**
    (스키마 전용 > 대상 전용 > 전역, 2026-10-06 스키마 범위 추가), 같은 범위 안에서는 id 가
    작은 것. 결과는 원래 순서(id 순)를 유지한다.

    canonicalize_sql_verbose 는 SQL 을 한 번만 파싱하고 모든 규칙의 편집을 같은 원본 트리에
    모아 적용한다. 그래서 같은 종류가 둘이면 둘 다 편집을 낸다 — 실측(2026-10-02): BIRD 의
    order_by_nulls(sqlite)에 전역 order_by_nulls(desc_last)를 더하자 `DESC NULLS LAST NULLS LAST`
    문법 오류가 났다. 뒤 규칙의 "이미 NULLS 절이 있으면 건너뜀"은 원본 트리를 보므로 막지 못한다.
    """
    chosen: dict[Any, Rule] = {}
    for r in rule_defs:
        if r.rule_type != "canonicalization":
            continue
        kind = r.definition.get("kind") if isinstance(r.definition, dict) else ("__bad__", r.id)
        prev = chosen.get(kind)
        if prev is None:
            chosen[kind] = r
        elif _scope_rank(r) > _scope_rank(prev):
            logger.info("canonicalization %s: 좁은 범위 규칙 id=%s 가 id=%s 를 대신합니다", kind, r.id, prev.id)
            chosen[kind] = r
        else:
            logger.info("canonicalization %s: 규칙 id=%s 는 id=%s 와 종류가 같아 건너뜁니다", kind, r.id, prev.id)
    keep = {id(r) for r in chosen.values()}
    return [r for r in rule_defs if id(r) in keep]


def load_rules_from_store(
    rule_defs: list[Rule],
    column_owners: dict[str, set[str]] | None = None,
    question: str | None = None,
    evidence: str | None = None,
    canonical_copies: dict[tuple[str, str], tuple[str, str]] | None = None,
    pk_columns: dict[str, set[str]] | None = None,
    timestamp_columns: dict[str, set[str]] | None = None,
) -> list[CanonRule]:
    """governance.rules.SqlRuleStore에서 읽은 정의(dict)를 CanonRule 인스턴스로 변환.

    잘못된 정의 하나가 전체 SQL 생성을 막으면 안 된다(설계 원칙 1: 보조 컴포넌트가
    죽어도 필수 경로는 성립). 실측 사고: `definition`을 jsonb 컬럼에 이중 인코딩해
    저장하는 바람에 dict가 아닌 str로 읽혔고, `.get()`에서 터진 예외가 그대로 올라가
    BIRD 30문항이 전부 "'str' object has no attribute 'get'"으로 실패했다.
    """
    rules: list[CanonRule] = []
    for r in _one_per_kind(rule_defs):
        made_before = len(rules)
        if not isinstance(r.definition, dict):
            logger.warning(
                "canonicalization 규칙 id=%s의 definition이 dict가 아니라 %s입니다 — 건너뜁니다. "
                "jsonb 이중 인코딩(코덱이 등록된 커넥션에 json.dumps() 결과를 넘김)일 수 있습니다.",
                r.id, type(r.definition).__name__,
            )
            continue
        kind = r.definition.get("kind")
        if kind == "ensure_limit":
            rules.append(EnsureLimitRule(default_limit=r.definition.get("default_limit", 1000)))
        elif kind == "order_by_nulls":
            rules.append(OrderByNullsRule(mode=r.definition.get("mode", "desc_last")))
        elif kind == "order_by_tiebreak":
            rules.append(OrderByTiebreakRule())
        elif kind == "canonical_column":
            # 스키마 분석(Design Lab)이 있어야 판정할 수 있는 규칙 — 호출자가 사본
            # 매핑을 주지 않으면 조용히 건너뛴다(설계 원칙 1).
            #
            # `rewrite: false`면 사본 맵은 계산하되 **SQL을 고치지는 않는다.** 맵 자체는
            # `redundant_join` 가드가 "이 컬럼이 다른 테이블에도 있는가"를 판정하는 데
            # 쓰므로, 재작성만 끄고 싶을 때 규칙을 통째로 비활성하면 가드까지 죽는다.
            if r.definition.get("rewrite") is False:
                logger.info("canonical_column 규칙 id=%s: rewrite=false — 교정을 건너뜁니다", r.id)
            elif canonical_copies:
                rules.append(CanonicalColumnRule(canonical_copies))
            else:
                logger.info("canonical_column 규칙 id=%s: 사본 매핑이 없어 건너뜁니다", r.id)
        elif kind == "alias_fix":
            # 스키마를 알아야 판정할 수 있는 규칙 — 호출자가 column_owners를 주지 않으면
            # 조용히 건너뛴다(설계 원칙 1: 보조 기능이 없다고 필수 경로가 막히면 안 된다).
            if column_owners:
                rules.append(AliasFixRule(column_owners))
            else:
                logger.warning("alias_fix 규칙 id=%s: column_owners가 없어 건너뜁니다", r.id)
        elif kind == "distinct_when_list_all":
            if question:
                rules.append(DistinctWhenListAllRule(question))
        elif kind == "column_order":
            # 질문 텍스트가 있어야 판정할 수 있다 — SQL 직접 실행 경로처럼 질문이 없는
            # 호출에서는 조용히 건너뛴다.
            if question:
                rules.append(ColumnOrderRule(
                    question, evidence, on_conflict=r.definition.get("on_conflict", "skip"),
                ))
            else:
                logger.debug("column_order 규칙 id=%s: 질문이 없어 건너뜁니다", r.id)
        elif kind == "dedupe_columns":
            rules.append(DedupeColumnsRule())
        elif kind == "distinct_single_column":
            cols = r.definition.get("columns")
            rules.append(DistinctSingleColumnRule(pk_columns, cols if isinstance(cols, list) else None))
        elif kind == "yes_no_upper":
            rules.append(YesNoUpperRule())
        elif kind == "single_table_no_alias":
            rules.append(SingleTableNoAliasRule())
        elif kind == "subquery_eq_to_in":
            rules.append(SubqueryEqToInRule())
        elif kind == "date_part_func":
            rules.append(DatePartFuncRule())
        elif kind == "round_numeric":
            rules.append(RoundNumericRule())
        elif kind == "cast_float":
            rules.append(CastFloatRule([str(c) for c in r.definition.get("columns") or []]))
        elif kind == "count_groups":
            if question:
                rules.append(CountGroupsRule(question))
        elif kind == "date_literal_compare":
            # 컬럼 타입을 알아야 하는 규칙 — 호출자가 주지 않으면 건너뛴다(설계 원칙 1).
            if timestamp_columns:
                rules.append(DateLiteralCompareRule(timestamp_columns))
            else:
                logger.info("date_literal_compare 규칙 id=%s: timestamp 컬럼 정보가 없어 건너뜁니다", r.id)
        for made in rules[made_before:]:
            made.source_rule_id = r.id
    return rules


# canonical_rewrite 단계가 LLM 실패 시 폴백으로 쓰는 표. 스키마·질문 같은 바깥 맥락
# 없이 만들어지는 규칙만 여기 둔다 — 폴백은 "LLM이 못 했으니 코드가 확정한다"는
# 자리라, 맥락이 없어 조용히 건너뛰는 규칙을 두면 폴백이 아무 일도 안 한 게 된다.
_FALLBACK_RULES: dict[str, Any] = {
    "dedupe_columns": DedupeColumnsRule,
    "ensure_limit": EnsureLimitRule,
}


def build_fallback_rule(kind: str) -> CanonRule | None:
    """`kind` 이름으로 CanonRule 하나를 만든다. 폴백으로 쓸 수 없는 종류면 None."""
    factory = _FALLBACK_RULES.get(kind)
    return factory() if factory is not None else None


def canonicalize_sql_verbose(
    sql: str, parser: SqlParser, rules: list[CanonRule],
) -> tuple[str, list[str]]:
    """정규화 결과와 **실제로 편집을 낸 규칙들의 라벨**을 함께 돌려준다.

    규칙을 뺄지 말지 판단하려면 "프롬프트에 있었다"가 아니라 "일했다"를 세야 한다.
    `canonicalize_sql()`은 결과만 필요한 호출자를 위한 얇은 껍데기다.
    """
    stmt = parser.parse(sql)
    if not stmt.is_well_formed:
        # 문법 오류가 있으면 ANTLR이 복구하면서 트리 일부를 버린다 — 그 트리의 토큰
        # 인덱스로 원문을 재작성하면 엉뚱한 위치를 건드려 SQL을 더 망가뜨린다.
        # 원문을 그대로 돌려주고 판단은 검증 계층(§5.9)에 맡긴다.
        return sql, []
    edits: list[TokenEdit] = []
    applied: list[str] = []
    # 같은 편집(같은 자리에 같은 글자)은 한 번만 — 규칙들은 모두 **원본 트리**를 보므로 서로의 편집을
    # 모른다. 규칙 44(단일 컬럼 DISTINCT)와 48(List all DISTINCT)이 둘 다 SELECT 뒤에 " DISTINCT" 를
    # 넣어 `SELECT DISTINCT DISTINCT` 문법 오류가 났다(2026-10-14 run 420, card seq 389).
    seen: set[tuple] = set()
    for rule in rules:
        got = [e for e in rule.collect_edits(stmt)
               if (e.kind, e.start_token_index, e.end_token_index, e.text) not in seen]
        if got:
            applied.append(rule.label())
            for e in got:
                seen.add((e.kind, e.start_token_index, e.end_token_index, e.text))
            edits.extend(got)
    if not edits:
        return sql, []
    return parser.rewrite(sql, edits), applied


def canonicalize_sql(sql: str, parser: SqlParser, rules: list[CanonRule]) -> str:
    return canonicalize_sql_verbose(sql, parser, rules)[0]
