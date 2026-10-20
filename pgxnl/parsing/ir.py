"""SQL 절 단위 정규화 IR (docs/pgxnl_antlr_pipeline_design.md §2 참고).

이 모듈은 ANTLR에 의존하지 않는다 — dataclass와 정규화 규칙만 담는다. 실제 추출은
parsing/ir_builder.py가 하고, 진입점은 SqlParser.to_ir()이다. base.py와 같은 원칙:
IR을 소비하는 쪽(평가 하네스, Rule validator)은 grammar 세부사항을 몰라야 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 작은따옴표 문자열 리터럴('' 이스케이프 포함). 리터럴 안쪽은 소문자화하면 안 된다 —
# WHERE city = 'Seoul'을 'seoul'로 바꾸면 gold와의 값 비교가 깨진다.
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")
_WHITESPACE_RE = re.compile(r"\s+")
# 비교 목적의 표준형에서는 구두점·연산자 주변 공백이 의미가 없다. `count( * )`와
# `count(*)`, `a > b`와 `a>b`가 같은 것으로 취급되어야 집합 비교가 성립한다.
# 이 결과물은 비교 키로만 쓰이고 다시 SQL로 실행되지 않으므로, `a - -1`이 `a--1`처럼
# 문법적으로 이상해 보이는 형태가 되어도 무방하다(gold/pred 양쪽에 동일 적용된다).
_PUNCT_SPACE_RE = re.compile(r"\s*([(),<>=!+*/%|-])\s*")


def normalize_expr(text: str) -> str:
    """표현식 문자열을 비교 가능한 표준형으로.

    - 식별자는 소문자화하고 큰따옴표를 제거한다 (PostgreSQL은 인용 없는 식별자를
      소문자로 접으므로 `Score`와 `score`는 같은 컬럼이다)
    - 문자열 리터럴은 대소문자와 내부 공백을 그대로 보존한다
    - 리터럴 밖에서만 공백을 접는다
    """
    parts: list[str] = []
    pos = 0
    for m in _STRING_LITERAL_RE.finditer(text):
        parts.append(_normalize_segment(text[pos : m.start()]))
        parts.append(m.group(0))
        pos = m.end()
    parts.append(_normalize_segment(text[pos:]))
    return "".join(parts).strip()


def _normalize_segment(segment: str) -> str:
    """리터럴 바깥 구간에만 적용되는 정규화. 리터럴 안쪽에 이 규칙을 적용하면
    `'a > b'` 같은 값의 내용이 바뀌어 비교가 틀어진다."""
    folded = segment.lower().replace('"', "")
    collapsed = _WHITESPACE_RE.sub(" ", folded)
    return _PUNCT_SPACE_RE.sub(r"\1", collapsed)


@dataclass
class SelectItem:
    expr: str  # 정규화된 표현식
    alias: str | None = None

    def __str__(self) -> str:  # 디버그 출력용
        return f"{self.expr} AS {self.alias}" if self.alias else self.expr


@dataclass
class PredicateNode:
    """WHERE/HAVING/ON의 불리언 트리.

    op: 'AND' | 'OR' | 'NOT' | 'CMP' | 'RAW'
      - AND/OR/NOT은 children을 갖는다
      - CMP는 left/comparator/right를 갖는다 (a = b, a > b 등)
      - RAW는 아직 구조 분해하지 않은 잎(IN, LIKE, BETWEEN, IS NULL, 서브쿼리 등)으로
        left에 정규화된 원문 전체가 들어간다. 구조 비교에서는 문자열로 취급된다.
    """

    op: str
    children: list[PredicateNode] = field(default_factory=list)
    left: str | None = None
    comparator: str | None = None
    right: str | None = None

    def flatten_and(self) -> list[PredicateNode]:
        """AND로만 묶인 최상위 조건들을 잎 리스트로 편다.

        설계 문서 §3.2의 "AND 트리는 leaf 집합으로 flatten 후 비교"에 대응한다.
        OR가 섞이면 그 하위는 순서가 의미를 가지므로 통째로 하나의 잎으로 남긴다.
        """
        if self.op != "AND":
            return [self]
        out: list[PredicateNode] = []
        for child in self.children:
            out.extend(child.flatten_and())
        return out

    def signature(self) -> str:
        """집합 비교에 쓰는 문자열 표현. CMP는 교환법칙을 적용해 좌우를 정렬한다 —
        `a.id = b.id`와 `b.id = a.id`는 같은 조건이다."""
        if self.op == "CMP":
            left, right = self.left or "", self.right or ""
            if self.comparator == "=" and right < left:
                left, right = right, left
            return f"{left}{self.comparator}{right}"
        if self.op == "RAW":
            return self.left or ""
        inner = sorted(c.signature() for c in self.children) if self.op == "AND" else [
            c.signature() for c in self.children
        ]
        return f"{self.op}({','.join(inner)})"


@dataclass
class JoinNode:
    table: str
    join_type: str  # 'INNER' | 'LEFT' | 'RIGHT' | 'FULL' | 'CROSS' | 'NATURAL'
    on: PredicateNode | None = None
    using: list[str] = field(default_factory=list)

    def signature(self) -> str:
        on_sig = self.on.signature() if self.on else ",".join(sorted(self.using))
        return f"{self.join_type}:{self.table}:{on_sig}"


@dataclass
class QueryIR:
    """최상위 SELECT 한 개의 절 단위 표현.

    서브쿼리와 집합연산(UNION 등)은 v1에서 구조 분해하지 않고 플래그로만 표시한다
    (설계 문서 §7 1단계: SELECT/FROM/WHERE 우선). 비교 로직이 이 플래그를 보고
    "구조 비교 신뢰 불가"로 처리할 수 있게 하기 위함이다.
    """

    select_items: list[SelectItem] = field(default_factory=list)
    from_tables: list[str] = field(default_factory=list)
    joins: list[JoinNode] = field(default_factory=list)
    where: PredicateNode | None = None
    group_by: list[str] = field(default_factory=list)
    having: PredicateNode | None = None
    order_by: list[tuple[str, str]] = field(default_factory=list)  # (expr, 'ASC'|'DESC')
    limit: int | None = None
    offset: int | None = None
    distinct: bool = False
    # 구조 비교의 신뢰도를 낮추는 요인들 — 설계 문서 §8의 열린 질문에 대응한다.
    has_subquery: bool = False
    set_operation: str | None = None  # 'UNION' | 'INTERSECT' | 'EXCEPT'

    @property
    def is_simple(self) -> bool:
        """서브쿼리·집합연산이 없어 절 단위 구조 비교를 신뢰할 수 있는가."""
        return not self.has_subquery and self.set_operation is None
