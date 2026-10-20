"""SQL 파서 공통 인터페이스.

design 문서 §6(SQL 파서) / ADR-0002 참고. pgxnl/agent/canonicalize.py,
validation.py, discovery/join_history.py는 이 인터페이스만 사용하며 ANTLR
구현 세부사항(grammar, 생성 코드)에 의존하지 않는다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SqlKind(Enum):
    SELECT = "select"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    DDL = "ddl"
    OTHER = "other"


@dataclass
class JoinCondition:
    table_a: str
    column_a: str
    table_b: str
    column_b: str


@dataclass
class ParsedStatement:
    kind: SqlKind
    referenced_tables: list[str]
    joins: list[JoinCondition]
    raw_tree: Any  # 구현체별 ANTLR ParseTree — Canonicalization 규칙 등에서 필요 시 사용
    # to_ir()이 원본 문자열 구간을 슬라이스하는 데 쓴다. 기존 호출부는 이 필드를
    # 넘기지 않으므로 기본값을 둔다.
    source_sql: str | None = None
    # 별칭/테이블명 -> 정규화된 테이블명. AliasFixRule처럼 "이 별칭이 어느 테이블인가"를
    # 알아야 하는 규칙이 쓴다. 파서가 이미 계산하고 있던 것을 노출만 한 것이다.
    alias_to_table: dict[str, str] = field(default_factory=dict)
    # ANTLR이 보고한 문법 오류. **비어 있지 않으면 이 문장의 파싱 결과를 믿으면 안 된다** —
    # ANTLR은 오류를 만나면 예외를 던지지 않고 복구해서 트리 일부를 버리므로,
    # referenced_tables/alias_to_table/joins가 조용히 불완전해진다(실측: `SELECT a FROM
    # schools LIMIT 1 HAVING COUNT(*) > 5`가 예외 없이 kind=SELECT, tables=['schools']로
    # 파싱된다). 검증 계층은 이걸 보고 거부해야 한다 — 바인딩을 신뢰할 수 없는 상태에서
    # 통과시키면 문법 커버리지 구멍이 그대로 거버넌스 구멍이 된다.
    syntax_errors: list[str] = field(default_factory=list)
    #: 한 별칭이 서로 다른 테이블에 묶인 경우 그 별칭들. `alias_to_table`은 스코프를
    #: 구분하지 않는 평면 dict라, 서브쿼리가 바깥과 같은 별칭을 다른 테이블에 쓰면
    #: 안쪽이 바깥을 **조용히 덮어쓴다**(실측: `SELECT a.x FROM frpm AS a WHERE a.y >
    #: (SELECT max(a.z) FROM schools AS a)` -> `{'a': 'schools'}`). 컬럼을 고쳐 쓰는
    #: 규칙은 이 경우 손대면 안 된다 — 바깥 `a.x`를 schools로 오해해 조용한 오답을
    #: 만든다. 비어 있으면 별칭 바인딩을 스코프와 무관하게 신뢰해도 된다.
    ambiguous_aliases: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_well_formed(self) -> bool:
        return not self.syntax_errors


class SqlParser(ABC):
    """PostgreSQL 문법으로 SQL을 파싱하는 공통 인터페이스 (§6)."""

    @abstractmethod
    def parse(self, sql: str) -> ParsedStatement: ...

    def to_ir(self, stmt: ParsedStatement) -> Any | None:
        """이미 파싱된 문장에서 절 단위 IR(parsing/ir.py의 QueryIR)을 만든다.

        parse()가 채워 준 raw_tree를 재사용하므로 같은 SQL을 두 번 파싱하지 않는다.
        IR은 평가 하네스의 구조 비교와 Rule validator가 쓰며, 그쪽은 grammar를 모른다
        (docs/pgxnl_antlr_pipeline_design.md §2). SELECT가 아니면 None.

        반환 타입을 QueryIR로 명시하지 않은 것은 base.py가 ir.py에 의존하지 않게 하려는
        게 아니라 순환 import를 피하기 위함이다 — 구현체는 QueryIR을 반환한다.
        """
        raise NotImplementedError

    @abstractmethod
    def rewrite(self, sql: str, edits: list[TokenEdit]) -> str:
        """TokenStreamRewriter 기반 국소 patch. §6 "SQL 재생성 전략" 참고.

        구조적 재작성(SELECT 절 재배열 등)이 필요하면 이 메서드 대신 Visitor로
        AST를 순회하며 문자열을 처음부터 재조립하는 별도 경로를 구현한다.
        """


@dataclass
class TokenEdit:
    """TokenStreamRewriter에 적용할 국소 편집 하나.

    kind: 'insert_after' | 'insert_before' | 'replace' | 'delete'
    """

    kind: str
    start_token_index: int
    end_token_index: int | None = None
    text: str | None = None
