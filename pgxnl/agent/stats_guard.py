"""생성된 SQL이 **데이터의 실제 분포와 맞는지** 검사한다. ADR-0009 / design 문서 §5.9 참고.

`question_guard`와 짝을 이루지만 근거가 다르다:

- `question_guard` — SQL ↔ **질문 텍스트** 대조. 데이터도 스키마도 안 보므로 비용이 0이고
  데이터가 바뀌어도 낡지 않는다.
- `stats_guard`(이 모듈) — SQL ↔ **컬럼 통계** 대조. `pg_stats`를 읽으므로 ANALYZE 시점에
  의존하고, 데이터가 바뀌면 판정도 바뀐다.

첫 검사는 "사실상 비어 있는 컬럼"이다. 질문이 값의 존재를 요구하는데(`valid e-mail
addresses`) 모델이 거의 전부 NULL인 컬럼을 SELECT에 넣으면, 결과에 NULL 열이 하나
붙는다. 실측(california_schools.schools):

    admemail1  null_frac 0.340
    admemail2            0.976
    admemail3            0.998   <- 17,686행 중 약 42행에만 값이 있다

`null_frac`은 `pg_stats`에 이미 계산돼 있어 테이블 스캔이 없다(ADR-0007과 같은 이유로
통계를 새로 만들지 않고 재사용한다).

**컬럼을 코드가 지우지 않는다.** ReAct 루프에 관찰로 돌려주고 모델이 다시 판단하게 한다 —
`question_guard`의 리터럴 검사와 같은 원칙이다. 모델이 의도적으로 넣은 컬럼까지 코드가
덮어쓰면 조용한 오답이 되고, `null_frac`이 높다는 것은 "틀렸다"가 아니라 "이상하다"는
신호일 뿐이다.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pgxnl.parsing.ir import QueryIR

logger = logging.getLogger(__name__)

#: 컬럼 통계 조회 콜백. (schema, table, column) -> null_frac (없으면 None).
#: 조회 실패는 예외를 던져도 된다 — 호출자가 "판단 불가"로 처리한다.
NullFracLookup = Callable[[str, str, str], Awaitable[float | None]]

#: 값이 "흔한 값"으로 등장하는 컬럼들을 찾는 콜백. (schema, value) -> ["table.column", ...]
ValueColumnLookup = Callable[[str, str], Awaitable[list[str]]]

#: 규칙에 threshold가 없을 때 쓰는 기본값.
#:
#: 처음에 0.95로 뒀다가 실측에서 틀린 것을 확인해 올렸다. BIRD 467의 gold는
#: `AdmEmail2`(null_frac 0.976)를 **남긴다** — 0.95면 gold가 유지한 컬럼까지 지적하는
#: 오탐이 된다. 반복 그룹 컬럼은 0.97~0.99 사이에 몰려 있어서 임계값 한 자리가 판정을
#: 가른다(admemail1 0.340 / admemail2 0.976 / admemail3 0.998).
#:
#: 0.99는 "백 행에 하나꼴로만 값이 있다"는 뜻이다. 이 정도면 그 컬럼을 SELECT에 넣어도
#: 거의 항상 NULL 열이 하나 붙는다. 스키마마다 분포가 다르므로 규칙에서 덮어쓸 수 있다.
DEFAULT_THRESHOLD = 0.99

#: `별칭.컬럼` 한정 참조만 본다 — 한정하지 않은 컬럼은 어느 테이블 것인지 정하려면
#: 스코프 분석이 필요하고, 잘못 판단하면 멀쩡한 SQL에 경고를 단다(`_bind_columns`와 같은 판단).
_QUALIFIED_COLUMN = re.compile(r'^"?([\w]+)"?\.\"?([^".]+)"?$')

_ASCII_TRIGGER = re.compile(r"^[\w\s'-]+$", re.ASCII)


@dataclass
class EmptyColumnWarning:
    """질문이 값의 존재를 요구하는데 SELECT에 사실상 비어 있는 컬럼이 들어 있다."""

    expr: str  # SQL에 쓰인 표기 (`t2.admemail3`)
    table: str
    column: str
    null_frac: float
    trigger: str  # 이 검사를 발동시킨 질문 속 낱말

    def message(self) -> str:
        return (
            f"{self.expr} 은(는) 값의 {self.null_frac * 100:.1f}%가 NULL입니다 "
            f"({self.table}.{self.column}). 질문은 '{self.trigger}'을(를) 요구했습니다 — "
            f"이 컬럼을 결과에 포함하는 것이 맞는지 다시 판단하세요."
        )


def triggered_by(question: str, triggers: list[str]) -> str | None:
    """질문에 검사를 발동시킬 낱말이 있으면 그 낱말을 돌려준다.

    영문은 낱말 경계로 본다 — `valid`가 `invalid`(뜻이 정반대)나 `validity`(BIRD 474에서는
    `duration > 12`로 NULL과 무관하다)에 걸리면 안 된다. 한글은 낱말 경계(`\\b`)가 의도대로
    동작하지 않으므로 부분 문자열로 본다.
    """
    for raw in triggers:
        trigger = raw.strip()
        if not trigger:
            continue
        if _ASCII_TRIGGER.match(trigger):
            if re.search(rf"\b{re.escape(trigger)}\b", question, re.IGNORECASE):
                return trigger
        elif trigger.lower() in question.lower():
            return trigger
    return None


def _split_qualified(expr: str) -> tuple[str, str] | None:
    """SELECT 항목에서 `별칭.컬럼`만 뽑는다. 집계·계산식(`count(*)`, `a / b`)은 제외한다 —
    식의 결과가 NULL인지는 컬럼 통계로 판단할 수 없다."""
    expr = expr.strip()
    if any(ch in expr for ch in "()+-*/,"):
        return None
    m = _QUALIFIED_COLUMN.match(expr)
    return (m.group(1).lower(), m.group(2).strip().lower()) if m else None


async def check_empty_columns(
    ir: QueryIR, *, question: str, alias_to_table: dict[str, str], lookup: NullFracLookup,
    triggers: list[str], threshold: float = DEFAULT_THRESHOLD, default_schema: str = "public",
) -> list[EmptyColumnWarning]:
    """SELECT에 사실상 비어 있는 컬럼이 있으면 신고한다. 없으면 빈 리스트.

    서브쿼리가 있으면 통째로 건너뛴다 — `alias_to_table`이 스코프를 구분하지 못해 바깥
    질의의 별칭으로 안쪽 컬럼을 조회하게 된다(`_bind_columns`와 같은 이유).
    """
    trigger = triggered_by(question, triggers)
    if trigger is None or not ir.is_simple or not alias_to_table:
        return []

    aliases = {a.lower(): t for a, t in alias_to_table.items()}
    found: list[EmptyColumnWarning] = []
    seen: set[str] = set()

    for item in ir.select_items:
        parsed = _split_qualified(item.expr)
        if parsed is None:
            continue
        alias, column = parsed
        qualified = aliases.get(alias)
        if qualified is None or f"{alias}.{column}" in seen:
            continue
        seen.add(f"{alias}.{column}")
        schema, _, table = qualified.rpartition(".")
        try:
            null_frac = await lookup(schema or default_schema, table, column)
        except Exception:  # 통계 조회 실패는 "판단 불가"이지 신고 사유가 아니다
            logger.debug("컬럼 통계 조회 실패: %s.%s", table, column, exc_info=True)
            continue
        # ANALYZE가 안 돌았으면 통계 자체가 없다. 없는 것을 "비어 있다"로 읽으면 안 된다.
        if null_frac is None or null_frac < threshold:
            continue
        found.append(EmptyColumnWarning(
            expr=item.expr.strip(), table=table, column=column, null_frac=null_frac, trigger=trigger,
        ))
    return found


def parse_rule(definition: dict[str, Any]) -> tuple[list[str], float] | None:
    """`stats_guard` 규칙 정의에서 (트리거 낱말들, 임계값)을 꺼낸다.

    트리거가 비어 있으면 None을 돌려준다 — 그 규칙은 어떤 질문에도 발동하지 않으므로
    켜 두는 의미가 없고, 조용히 전부 발동하게 만드는 것이 더 위험하다.
    """
    triggers = definition.get("trigger") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    triggers = [t for t in triggers if isinstance(t, str) and t.strip()]
    if not triggers:
        return None
    try:
        threshold = float(definition.get("threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD
    return triggers, threshold


# ------------------------------------------------- 값이 여러 컬럼에 있을 때 (컬럼 선택 모호)


@dataclass
class AmbiguousColumnValue:
    """필터에 쓴 값이 다른 컬럼에서도 흔한 값이다 — 컬럼 선택이 모호하다."""

    literal: str
    used: str  # SQL이 쓴 컬럼 (`t2.city`)
    candidates: list[str]  # 그 값을 흔한 값으로 갖는 컬럼들 ("schools.county" 등)

    def message(self) -> str:
        return (
            f"'{self.literal}' 은(는) {', '.join(self.candidates)} 에서도 흔한 값입니다. "
            f"SQL은 {self.used} 를 썼습니다 — 질문이 어느 쪽을 뜻하는지 다시 판단하세요."
        )


async def check_ambiguous_columns(
    ir: QueryIR, *, alias_to_table: dict[str, str], lookup: ValueColumnLookup,
    schema: str, min_length: int = 4,
) -> list[AmbiguousColumnValue]:
    """필터 값이 여러 컬럼에서 흔한 값이면 신고한다. 없으면 빈 리스트.

    실측 배경(BIRD 445) — 질문은 "high schools in Monterey"라고만 하는데 `Monterey`는
    다섯 컬럼에 존재한다:

        schools.county 247 / frpm."County Name" 130 / satscores.cname 27
        schools.mailcity 17 / schools.city 16

    모델은 `city`(16행)를 골랐고 gold는 `county`(247행)다. 질문·evidence·스키마 어디에도
    근거가 없고 **데이터를 봐야** 갈린다.

    후보는 `pg_stats`의 최빈값(MCV)으로 찾는다. MCV는 상위 100개뿐이라 저카디널리티
    컬럼만 잡히는데, 그게 의도한 방향이다 — "58개 카운티 중 하나"는 범주를 뜻하지만
    "1165개 도시 중 하나"는 약한 신호다. 조회도 pg_stats 한 번이면 끝나 값싸다.

    **판정하지 않는다.** 행 수가 많은 쪽을 권하지 않고 사실만 돌려준다. 30문항 실측에서
    gold는 13건 모두 후보 안의 컬럼을 썼지만(오탐 0), "최다 컬럼이 정답"은 표본 밖에서
    보장되지 않는다. 같은 뜻의 컬럼이 두 테이블에 있는 경우(`schools.soctype` 1776 vs
    `frpm."School Type"` 1331)는 행 수로 가릴 수 없다.
    """
    if not ir.is_simple or not alias_to_table:
        return []
    aliases = {a.lower(): t for a, t in alias_to_table.items()}
    found: list[AmbiguousColumnValue] = []
    seen: set[str] = set()

    for literal, column in _filter_values(ir.where) + _filter_values(ir.having):
        if len(literal) < min_length or literal in seen or not column:
            continue
        seen.add(literal)
        try:
            candidates = await lookup(schema, literal)
        except Exception:  # 조회 실패는 "판단 불가"
            logger.debug("값 컬럼 조회 실패: %s", literal, exc_info=True)
            continue
        if len(candidates) < 2:
            continue
        alias, _, name = column.rpartition(".")
        table = aliases.get(alias.strip().strip('"').lower(), "")
        used_col = name.strip().strip('"').lower()
        qualified = f"{table.rsplit('.', 1)[-1]}.{used_col}"
        # SQL이 쓴 컬럼이 후보 안에 있으면 이미 흔한 값을 쓴 것이다 — 알릴 게 없다.
        if any(c.lower() == qualified.lower() for c in candidates):
            continue
        found.append(AmbiguousColumnValue(
            literal=literal, used=column.strip(), candidates=candidates,
        ))
    return found


def _filter_values(node: Any) -> list[tuple[str, str | None]]:
    """WHERE/HAVING에서 (문자열 리터럴, 비교된 컬럼)을 모은다."""
    if node is None:
        return []
    out: list[tuple[str, str | None]] = []
    if node.op in ("AND", "OR", "NOT"):
        for child in node.children:
            out.extend(_filter_values(child))
        return out
    if node.right:
        column = (node.left or "").strip() or None
        out.extend((m.group(1), column) for m in re.finditer(r"'((?:[^']|'')*)'", node.right))
    return out
