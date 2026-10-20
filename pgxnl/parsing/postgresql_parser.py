"""ANTLR4 PostgreSQL grammar 기반 SqlParser 구현체.

grammar 생성 코드는 pgxnl/grammar/generated/ 아래에 있다 (pgxnl/grammar/README.md
참고. grammars-v4 PostgreSQL grammar 기반, ANTLR 4.13.2로 생성됨).
"""
from __future__ import annotations

import re

import antlr4
from antlr4.TokenStreamRewriter import TokenStreamRewriter

from pgxnl.grammar.generated.PostgreSQLLexer import PostgreSQLLexer
from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser
from pgxnl.grammar.generated.PostgreSQLParserListener import PostgreSQLParserListener
from pgxnl.parsing.base import JoinCondition, ParsedStatement, SqlKind, SqlParser, TokenEdit
from pgxnl.parsing.ir import QueryIR
from pgxnl.parsing.ir_builder import build_query_ir

_CHILD_KIND_MAP = {
    "SelectstmtContext": SqlKind.SELECT,
    "InsertstmtContext": SqlKind.INSERT,
    "UpdatestmtContext": SqlKind.UPDATE,
    "DeletestmtContext": SqlKind.DELETE,
}

_COMPARISON_OPS = (">=", "<=", "<>", "!=", "=", "<", ">")
#: 점으로 이어진 식별자 사슬. `t1.col` / `schema.table.col` / `t1."School Name"` 모두 잡는다.
#: 예전 `(\w+)\.(\w+)`는 **앞 두 조각만** 봐서 `california_schools.schools.cdscode`를
#: (테이블=california_schools, 컬럼=schools)로 오독했고, 따옴표 식별자는 통째로 놓쳤다.
_COLUMN_REF_RE = re.compile(r'(?:"[^"]+"|\w+)(?:\.(?:"[^"]+"|\w+))+')
_IDENT_PART_RE = re.compile(r'"[^"]+"|\w+')


def _split_ref(text: str) -> tuple[str, str] | None:
    """식별자 사슬에서 **마지막 두 조각**을 (테이블/별칭, 컬럼)으로 돌려준다.

    `schema.table.column`이면 (table, column), `alias.column`이면 (alias, column)이다.
    따옴표는 벗겨서 원래 대소문자를 살린다 — `"School Name"` 같은 컬럼이 있다.
    """
    parts = [p.strip('"') for p in _IDENT_PART_RE.findall(text)]
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def _normalize_table(name: str) -> tuple[str | None, str]:
    """'schema.table' -> (schema, table), 'table' -> (None, table)."""
    name = name.strip('"').strip("'").strip("`")
    parts = name.split(".")
    if len(parts) >= 2:
        return parts[-2].lower(), parts[-1].lower()
    return None, parts[0].lower()


class _StatementListener(PostgreSQLParserListener):
    """SELECT/JOIN/테이블 참조를 뽑아내는 최소 구현.

    relation_expr에서 테이블을, alias_clause에서 별칭을, join_qual의 ON 조건
    텍스트에서 (좌변 alias.column, 우변 alias.column) 첫 두 개를 등가조인으로
    추출한다. 복합 조건(AND로 묶인 다중 조건)은 첫 조건만 사용한다 — 실행이력
    기반 FK 발견(§5.3)의 신뢰도 가중치 입력으로 충분한 근사치다.
    """

    def __init__(self, sql: str) -> None:
        self._sql = sql
        self.tables: list[str] = []
        self.joins: list[JoinCondition] = []
        self._table_order: list[tuple[str | None, str]] = []
        # 별칭/테이블명 -> 정규화된 테이블명. join_qual의 등가조인 추출에 쓰고,
        # ParsedStatement.alias_to_table으로도 노출한다(AliasFixRule이 사용).
        self._alias_to_table: dict[str, str] = {}
        #: 별칭 -> 그 별칭이 묶인 모든 테이블. 평면 dict가 덮어쓰기로 잃는 정보를
        #: 여기 남겨 `ambiguous_aliases`로 노출한다.
        self._alias_bindings: dict[str, set[str]] = {}
        # WITH절로 정의한 이름(CTE)은 실제 카탈로그 테이블이 아니다 — 이걸 빼먹으면
        # `WITH total AS (...) SELECT ... FROM total`처럼 정상적인 CTE 참조를
        # "존재하지 않는 테이블(total)"로 오판해 검증 계층이 부당하게 거부하는 걸
        # 실측으로 확인했다(BIRD 문항 465번). CTE는 WITH절에서 참조 전에 먼저
        # 선언되므로(SQL 문법상 항상 그렇다), ANTLR의 기본 전위(pre-order) 순회
        # 순서상 enterCommon_table_expr이 그 이름을 쓰는 enterRelation_expr보다
        # 먼저 호출된다 — 별도 후처리 없이 이 집합만 먼저 채우면 된다.
        self._cte_names: set[str] = set()

    def enterCommon_table_expr(self, ctx: PostgreSQLParser.Common_table_exprContext) -> None:
        name_ctx = ctx.name()
        if name_ctx is not None:
            self._cte_names.add(name_ctx.getText().strip('"').lower())

    def enterRelation_expr(self, ctx: PostgreSQLParser.Relation_exprContext) -> None:
        qn = ctx.qualified_name()
        if qn is None:
            return
        schema, table = _normalize_table(qn.getText())
        if schema is None and table in self._cte_names:
            return  # CTE 참조 — 실제 테이블이 아니므로 존재 여부 검증 대상에서 제외
        qualified = f"{schema}.{table}" if schema else table
        self.tables.append(qualified)
        self._table_order.append((schema, table))
        self._alias_to_table.setdefault(table, qualified)
        self._alias_bindings.setdefault(table, set()).add(qualified)

    def enterAlias_clause(self, ctx: PostgreSQLParser.Alias_clauseContext) -> None:
        alias_text = ctx.colid().getText() if ctx.colid() else None
        if alias_text and self._table_order:
            schema, table = self._table_order[-1]
            qualified = f"{schema}.{table}" if schema else table
            self._alias_to_table[alias_text.lower()] = qualified
            self._alias_bindings.setdefault(alias_text.lower(), set()).add(qualified)

    def enterJoin_qual(self, ctx: PostgreSQLParser.Join_qualContext) -> None:
        if len(self._table_order) < 2:
            return
        expr = ctx.a_expr()
        if expr is None:
            return  # USING(...) 형태 — 등가조인 컬럼 쌍을 텍스트에서 추출할 수 없음
        # ctx.getText()는 토큰을 공백 없이 이어붙여 "b.idANDa.x"처럼 오염된다.
        # 원본 입력 스트림에서 문자 구간을 그대로 슬라이스해 원본 공백을 보존한다.
        condition_text = self._sql[expr.start.start : expr.stop.stop + 1]
        for op in _COMPARISON_OPS:
            condition_text = condition_text.replace(op, f" {op} ")
        found = [_split_ref(m) for m in _COLUMN_REF_RE.findall(condition_text)]
        refs = [r for r in found if r is not None]
        if len(refs) < 2:
            return
        (a_alias, a_col), (b_alias, b_col) = refs[0], refs[1]
        table_a = self._alias_to_table.get(a_alias.lower(), a_alias.lower())
        table_b = self._alias_to_table.get(b_alias.lower(), b_alias.lower())
        self.joins.append(
            JoinCondition(table_a=table_a, column_a=a_col, table_b=table_b, column_b=b_col)
        )


class _CollectingErrorListener(antlr4.error.ErrorListener.ErrorListener):
    """문법 오류를 모아두는 리스너.

    ANTLR 기본 리스너(ConsoleErrorListener)는 오류를 stderr로 직접 찍는다 — 평가
    로그에 `line 5:0 mismatched input 'HAVING' expecting <EOF>` 같은 줄이 섞여 나오고,
    SQL 조각이 콘솔로 새어 나간다. 기본 리스너를 떼고 이걸 붙여서, 오류를 출력하는
    대신 `ParsedStatement.syntax_errors`로 호출자에게 넘긴다.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []

    def syntaxError(self, recognizer, offending_symbol, line, column, msg, e) -> None:  # noqa: N802
        self.errors.append(f"{line}:{column} {msg}")


class AntlrPostgresParser(SqlParser):
    def _build_tree(
        self, sql: str
    ) -> tuple[antlr4.CommonTokenStream, PostgreSQLParser, PostgreSQLParser.RootContext, list[str]]:
        stream = antlr4.InputStream(sql)
        lexer = PostgreSQLLexer(stream)
        listener = _CollectingErrorListener()
        lexer.removeErrorListeners()
        lexer.addErrorListener(listener)
        tokens = antlr4.CommonTokenStream(lexer)
        tokens.fill()
        parser = PostgreSQLParser(tokens)
        parser.removeErrorListeners()
        parser.addErrorListener(listener)
        tree = parser.root()
        return tokens, parser, tree, listener.errors

    def parse(self, sql: str) -> ParsedStatement:
        _, _, tree, syntax_errors = self._build_tree(sql)

        stmts = tree.stmtblock().stmtmulti().stmt()
        kind = SqlKind.OTHER
        if len(stmts) == 1:
            child = stmts[0].getChild(0)
            child_name = type(child).__name__ if child is not None else ""
            kind = _CHILD_KIND_MAP.get(child_name, SqlKind.DDL)

        listener = _StatementListener(sql)
        walker = antlr4.ParseTreeWalker()
        walker.walk(listener, tree)

        stmt = ParsedStatement(
            kind=kind, referenced_tables=listener.tables, joins=listener.joins, raw_tree=tree,
            alias_to_table=dict(listener._alias_to_table),
            ambiguous_aliases=frozenset(
                a for a, tables in listener._alias_bindings.items() if len(tables) > 1
            ),
            # 여기서 예외를 던지지 않는다 — 파서는 라이브러리이고, 문법 커버리지가
            # 완벽하지 않은 상태에서 던지면 지금 동작하는 질의까지 죽는다. 대신 오류를
            # 실어 보내고, 보안 게이트인 검증 계층이 그걸 보고 거부한다(§5.9).
            syntax_errors=syntax_errors,
        )
        # 원문을 들고 있어야 to_ir()이 토큰 구간을 원본에서 슬라이스할 수 있다
        # (ctx.getText()는 공백을 잃어 `countdistinctid`처럼 오염된다).
        stmt.source_sql = sql
        return stmt

    def to_ir(self, stmt: ParsedStatement) -> QueryIR | None:
        if stmt.kind != SqlKind.SELECT or stmt.raw_tree is None:
            return None
        return build_query_ir(stmt.source_sql or "", stmt.raw_tree)

    def rewrite(self, sql: str, edits: list[TokenEdit]) -> str:
        tokens, _, _, _ = self._build_tree(sql)
        rewriter = TokenStreamRewriter(tokens)
        for edit in edits:
            if edit.kind == "insert_after":
                rewriter.insertAfter(edit.start_token_index, edit.text or "")
            elif edit.kind == "insert_before":
                # 파이썬 런타임의 insertBefore 는 첫 인자가 프로그램 이름이다 — 인덱스 버전을 쓴다.
                rewriter.insertBeforeIndex(edit.start_token_index, edit.text or "")
            elif edit.kind == "replace":
                rewriter.replaceRange(edit.start_token_index, edit.end_token_index, edit.text or "")
            elif edit.kind == "delete":
                # antlr4 파이썬 런타임에는 deleteRange가 없다(자바 쪽 이름이다).
                # 빈 문자열로 치환하면 같은 결과다.
                rewriter.replaceRange(edit.start_token_index, edit.end_token_index, "")
            else:
                raise ValueError(f"알 수 없는 TokenEdit.kind: {edit.kind}")
        return rewriter.getDefaultText()


def is_read_only(stmt: ParsedStatement) -> bool:
    """§5.9 검증 계층에서 사용하는 DML/DDL 차단 판정."""
    return stmt.kind == SqlKind.SELECT
