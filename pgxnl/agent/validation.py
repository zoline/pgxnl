"""SQL 검증 및 거버넌스 계층. design 문서 §5.9 / ADR-0006 참고.

Canonicalization을 거친 SQL이 실행되기 전 마지막으로 통과하는 계층. 전체가
결정론적 코드이며 LLM 호출이 없다 (§2.2 원칙). 캐시 히트로 SQL 생성을 건너뛴
경우에도 이 계층은 반드시 재통과해야 한다 — 캐시는 생성만 건너뛰는 것이지
권한 검사까지 건너뛰면 안 된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pgxnl.cache.schema import SchemaCache
from pgxnl.connectors.postgresql import PgConnector
from pgxnl.governance.glossary import GlossaryStore
from pgxnl.parsing.base import ParsedStatement, SqlParser
from pgxnl.parsing.postgresql_parser import is_read_only


class Decision(Enum):
    ALLOWED = "allowed"
    REJECTED = "rejected"
    CORRECTION_REQUESTED = "correction_requested"


@dataclass
class ValidationResult:
    decision: Decision
    reason: str | None = None
    estimated_cost: float | None = None


class ReadOnlyViolationError(Exception):
    """DML/DDL이 감지되어 즉시 거부해야 하는 경우."""


class SqlValidator:
    def __init__(
        self,
        parser: SqlParser,
        target_conn: PgConnector,
        glossary: GlossaryStore | None,
        *,
        max_cost: float,
        target_name: str,
        schema_cache: SchemaCache | None = None,
        default_schema: str = "public",
    ) -> None:
        self._parser = parser
        self._conn = target_conn
        self._glossary = glossary
        self._max_cost = max_cost
        self._target_name = target_name
        self._schema_cache = schema_cache
        self._default_schema = default_schema

    async def validate(self, sql: str, *, user_id: int) -> ValidationResult:
        stmt = self._parser.parse(sql)

        if not stmt.is_well_formed:
            # ANTLR은 문법 오류를 만나도 예외를 던지지 않고 복구해서 트리 일부를 버린다 —
            # 그러면 referenced_tables/alias_to_table이 조용히 불완전해지고, 아래의
            # 카탈로그/컬럼/PII 검사가 "볼 수 없었던 것"을 "문제 없음"으로 통과시킨다.
            # PG는 받아들이는데 우리 문법이 지원 못 하는 구문에서 특히 위험하다(SQL은
            # 정상 실행되는데 PII 탐지만 빠진다). 검증은 보안 게이트이므로 "판단 불가"를
            # 통과로 처리하면 안 된다 — 다른 검사(_bind_columns 등)가 조회 실패 시
            # 통과시키는 것과 방향이 반대인 이유가 이것이다.
            return ValidationResult(
                Decision.REJECTED,
                reason=f"SQL 구문을 해석할 수 없습니다: {'; '.join(stmt.syntax_errors[:3])}",
            )

        if not is_read_only(stmt):
            return ValidationResult(Decision.REJECTED, reason="read-only 위반: SELECT만 허용됩니다")

        catalog_result = await self._bind_catalog(stmt)
        if catalog_result is not None:
            return catalog_result

        column_result = await self._bind_columns(stmt)
        if column_result is not None:
            return column_result

        window_result = _reject_window_functions_in_filters(stmt)
        if window_result is not None:
            return window_result

        pii_hit = await self._flag_sensitive_columns(stmt)
        if pii_hit:
            # 정책에 따라 즉시 거부하거나 마스킹 후 허용할 수 있다. 여기서는 보수적으로 거부.
            return ValidationResult(Decision.REJECTED, reason=f"민감 컬럼 접근 감지: {pii_hit}")

        cost = await self._estimate_cost(sql, schema=self._default_schema)
        if cost is not None and cost > self._max_cost:
            return ValidationResult(
                Decision.REJECTED, reason="예상 비용 초과, 조건을 좁혀 주세요", estimated_cost=cost
            )

        return ValidationResult(Decision.ALLOWED, estimated_cost=cost)

    async def _bind_catalog(self, stmt: ParsedStatement) -> ValidationResult | None:
        """참조된 테이블이 실제 카탈로그에 존재하는지 확인. 존재하지 않으면 REJECTED.

        schema_cache가 없으면 (필수/보조 원칙에 따라) 검증을 건너뛴다 — 카탈로그
        바인딩은 방어 계층이지 필수 경로가 아니다.
        """
        if self._schema_cache is None:
            return None

        known_tables: dict[str, set[str]] = {}
        for qualified in stmt.referenced_tables:
            schema, _, table = qualified.rpartition(".")
            schema = schema or self._default_schema
            if schema not in known_tables:
                known_tables[schema] = await self._list_tables_cached(schema)
            if table not in known_tables[schema]:
                return ValidationResult(
                    Decision.REJECTED, reason=f"존재하지 않는 테이블을 참조했습니다: {qualified}"
                )
        return None

    async def _bind_columns(self, stmt: ParsedStatement) -> ValidationResult | None:
        """참조된 `별칭.컬럼`이 실제로 그 테이블에 있는지 확인. 없으면 REJECTED.

        `_bind_catalog`는 테이블만 본다 — 그래서 존재하지 않는 컬럼은 검증을 통과해
        실행 단계에서야 `column t1.charternum does not exist`로 터졌다(실측 run 103).
        `AliasFixRule`이 "별칭만 틀린" 경우는 사후 교정하지만, 아예 없는 컬럼명은
        아무도 잡지 못했다.

        **한정 참조(`별칭.컬럼`)만 본다.** 한정하지 않은 컬럼은 어느 테이블 것인지
        결정하려면 스코프 분석이 필요하고, 잘못 판단하면 정상 질의를 거부한다.
        서브쿼리가 있으면 alias_to_table이 스코프를 구분하지 못하므로 통째로 건너뛴다.
        """
        if self._schema_cache is None or not stmt.alias_to_table or stmt.raw_tree is None:
            return None

        from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
        from pgxnl.parsing.ir_builder import collect_contexts

        # CTE 도 같다 — CTE 별칭(cr)이 안쪽 테이블로 잘못 묶여 멀쩡한 `cr.revenue` 를 "order_details 에
        # 없는 컬럼"으로 거부했다(Northwind v2 run 567 seq 27·33, 모델 SQL 은 gold 와 일치).
        if collect_contexts(stmt.raw_tree, _P.Select_with_parensContext) \
                or collect_contexts(stmt.raw_tree, _P.Common_table_exprContext):
            return None

        alias_to_table = {a.lower(): t.rsplit(".", 1)[-1].lower() for a, t in stmt.alias_to_table.items()}
        columns: dict[str, set[str]] = {}
        for ref in collect_contexts(stmt.raw_tree, _P.ColumnrefContext):
            colid, indirection = ref.colid(), ref.indirection()
            if colid is None or indirection is None:
                continue
            alias = colid.getText().strip('"').lower()
            column = indirection.getText().lstrip(".").strip('"').lower()
            table = alias_to_table.get(alias)
            if table is None or not column or "*" in column:
                continue  # 별칭을 모르거나(스키마 한정 등) `t.*` 형태
            if table not in columns:
                columns[table] = await self._list_columns_cached(self._default_schema, table)
            if not columns[table]:
                continue  # 컬럼 목록을 못 가져왔다 — 판단 근거가 없으므로 통과시킨다
            if column not in columns[table]:
                return ValidationResult(
                    Decision.REJECTED,
                    reason=f"존재하지 않는 컬럼을 참조했습니다: {alias}.{indirection.getText().lstrip('.')} "
                           f"({table} 테이블에 없음)",
                )
        return None

    async def _list_columns_cached(self, schema: str, table: str) -> set[str]:
        cache_key = f"columns:{schema}.{table}"
        cached = await self._schema_cache.get(self._target_name, cache_key)
        if cached is not None:
            return set(cached)
        try:
            meta = await self._conn.describe_table(schema, table)
        except Exception:  # noqa: BLE001 — 조회 실패는 "판단 불가"이지 거부 사유가 아니다
            return set()
        names = [c.name.lower() for c in meta.columns]
        await self._schema_cache.set(self._target_name, cache_key, names)
        return set(names)

    async def _list_tables_cached(self, schema: str) -> set[str]:
        cache_key = f"tables:{schema}"
        cached = await self._schema_cache.get(self._target_name, cache_key)
        if cached is not None:
            return set(cached)
        tables = [t.name for t in await self._conn.list_tables(schema)]
        await self._schema_cache.set(self._target_name, cache_key, tables)
        return set(tables)

    async def _flag_sensitive_columns(self, stmt: ParsedStatement) -> set[str]:
        """참조된 테이블에 PII로 등록된 컬럼이 있으면 그 컬럼명을 반환한다.

        테이블 단위 판정이다 — SELECT/WHERE 절이 실제로 해당 컬럼을 참조하는지까지는
        확인하지 않는다(과잉 차단 가능, 과소 차단은 없음). 컬럼 단위 정밀화는
        용어집에 PII로 등록된 컬럼이 없는 한 아무 영향이 없으므로, 명시적으로
        PII를 등록한 target에서만 보수적으로 동작한다.
        """
        if self._glossary is None:
            return set()
        pii: set[str] = set()
        for qualified in stmt.referenced_tables:
            schema, _, table = qualified.rpartition(".")
            schema = schema or self._default_schema
            pii |= await self._glossary.pii_columns(self._target_name, schema, table)
        return pii

    async def _estimate_cost(self, sql: str, *, schema: str = "public") -> float | None:
        # PgConnector.explain()이 target DB 커넥션 풀에 jsonb 코덱이 등록되어 있지
        # 않은 문제를 처리해 파싱된 dict를 돌려준다 — 직접 execute_readonly로 raw
        # JSON 문자열을 받아 list로 취급하던 예전 코드는 항상 None을 반환했다.
        try:
            result = await self._conn.explain(sql, schema=schema)
        except Exception:  # noqa: BLE001
            return None
        return result["plan"].get("Total Cost")


#: PostgreSQL이 윈도우 함수를 금지하는 절. 윈도우 함수는 WHERE/GROUP BY/HAVING이
#: **끝난 뒤** 계산되므로 그 안에서 참조할 수 없다(ORDER BY와 SELECT는 허용).
#: 이 규칙을 어기면 실행 시점에 `window functions are not allowed in WHERE`로 터진다.
_WINDOW_FORBIDDEN_CLAUSES = ("WHERE", "GROUP BY", "HAVING", "JOIN ... ON")


def window_misuse_clause(stmt: ParsedStatement) -> str | None:
    """윈도우 함수가 금지된 절에 쓰였으면 그 절 이름을 반환한다.

    실측(BIRD seq 454, 8개 run에서 반복): 모델이 "카운티별 상위 5개"를 이렇게 쓴다 —

        WHERE T1.virtual = 'F'
          AND RANK() OVER (PARTITION BY T1.county ORDER BY ...) <= 5

    문법은 완전히 정상이라 파서도 검증도 통과하고, 실행 단계에서야 PG가 거부한다.
    같은 모델이 대안으로 시도한 `QUALIFY`는 Snowflake/DuckDB 문법이라 PG에 없다.
    정답은 서브쿼리로 감싸 바깥에서 필터하는 것이다.

    `_bind_columns`와 같은 계열의 검사다 — **실행하면 반드시 실패하는 SQL**을 미리
    잡아, 실행 오류 대신 고칠 방법이 담긴 사유를 돌려준다.
    """
    if stmt.raw_tree is None:
        return None

    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.ir_builder import collect_contexts

    for label, ctx_cls in (
        ("WHERE", _P.Where_clauseContext),
        ("GROUP BY", _P.Group_clauseContext),
        ("HAVING", _P.Having_clauseContext),
        ("JOIN ... ON", _P.Join_qualContext),
    ):
        for node in collect_contexts(stmt.raw_tree, ctx_cls):
            if collect_contexts(node, _P.Over_clauseContext):
                return label
    return None


def _reject_window_functions_in_filters(stmt: ParsedStatement) -> ValidationResult | None:
    clause = window_misuse_clause(stmt)
    if clause is None:
        return None
    return ValidationResult(
        Decision.REJECTED,
        reason=(
            f"{clause} 절에는 윈도우 함수(OVER)를 쓸 수 없습니다. "
            f"윈도우 함수를 서브쿼리의 SELECT에서 별칭으로 계산한 뒤, "
            f"바깥 쿼리의 WHERE에서 그 별칭으로 걸러 주세요. "
            f"예) SELECT c FROM (SELECT c, RANK() OVER (...) AS rnk FROM t WHERE ...) AS x WHERE x.rnk <= 5"
        ),
    )


async def record_audit_log(
    system_pool: Any, *, target_name: str, user_id: int, question: str | None,
    sql: str, decision: Decision, reason: str | None, estimated_cost: float | None,
) -> None:
    await system_pool.execute(
        """
        INSERT INTO pgxnl_audit_log
            (target_name, user_id, question, sql, decision, reason, estimated_cost)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        target_name, user_id, question, sql, decision.value, reason, estimated_cost,
    )
