"""예시 쌍으로 SQL을 고치는 뒤쪽 재작성 단계 (`rule_type='canonical_rewrite'`).

`canonicalization`과 **자리는 같고**(ReAct 루프가 끝난 뒤) **판정 주체가 다르다** —
저쪽은 파서, 이쪽은 LLM이다. 파서로 판정할 수 있으면 저쪽을 쓴다. 이 분류의 존재
이유는 두 가지다:

1. **파서로는 못 정하는데 SQL만 보면 사람은 아는** 변환이 있다(복합 질문의 분해 억제,
   조인 방향 등).
2. `canonicalization`은 하나 늘릴 때마다 `CanonRule` 서브클래스와 팩토리 분기를
   써야 한다. 이쪽은 **행 하나 추가로** 늘어난다.

프롬프트 앞이 아니라 뒤에 두는 이유는 실측이다(2026-09-10). BIRD 465용 지식을
few-shot으로 **앞에** 뒀더니 465는 얻었지만 444·447·452가 깨졌다(EX 28 -> 26) —
내용이 논리적으로 충돌해서가 아니라 텍스트가 늘어서다. 뒤에 두면 이미 만들어진 SQL만
보므로 테이블·컬럼 선택을 흔들 수 없다.

## 안전장치

LLM 재작성은 경계가 없다 — 필터 값 하나, 조인 하나를 조용히 바꿔도 SQL은 잘 실행되고
우리는 EX로만 알게 된다(실측: 444에서 `LIKE 'Riverside%'`의 `%`가 사라졌다). 그래서
**LLM이 제안하고 코드가 검증하고 어긋나면 원본을 쓴다.**

```
같아야 함:  참조 테이블 집합 · WHERE/HAVING/조인 조건의 리터럴 순서열
바뀌어도 됨: SELECT 목록 · 컬럼 순서
```

`column_rationale`이 이미 쓰는 패턴이다 — 모델에게 근거를 시키고, 그 근거가 실제로
질문에 있는지는 코드가 확인한다.

## 코드 폴백

LLM이 **수용되는 변경을 내놓지 못하면**(시간 초과·문법 오류·불변식 위반·아예 무변경)
`kind`가 지정한 파서 규칙이 대신 수행한다. 단계를 둘로 나누지 않고 여기서 끝내는
이유는 그게 더 단순하기 때문이다 — 순서를 고민할 필요가 없고, 무엇이 일했는지 한
자리에서 나온다.

"LLM이 고칠 게 없다고 했다"와 "LLM이 못 했다"를 구분하지 않는다. 구분해봐야 확인할
방법이 없고, 파서 구현이 있는 변환은 파서가 최종 판정을 갖는 편이 안전하다.

`kind`가 없는 규칙은 폴백 없이 원본을 쓴다 — 파서로 판정 불가한 변환(조인 방향 등)이
그렇다.

## 비용

질의당 LLM 호출 하나가 붙는다. `when_regex`가 있는 규칙은 SQL이 그 패턴에 걸릴 때만
후보가 되고, 후보가 하나도 없으면 **호출 자체를 하지 않는다**.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# 응답에서 SQL만 꺼낸다 — 모델이 ```sql 펜스나 설명을 붙이는 경우가 있다.
_FENCE = re.compile(r"```(?:sql)?\s*(.+?)\s*```", re.S | re.I)


@dataclass(frozen=True)
class RewriteExample:
    """`나쁜 SQL -> 좋은 SQL` 예시 하나."""

    bad_sql: str
    good_sql: str
    explanation: str = ""
    when_regex: str = ""
    #: LLM이 못 했을 때 대신 수행할 파서 규칙 이름(`canonicalize.build_fallback_rule`).
    #: 없으면 폴백 없이 원본을 쓴다 — 파서로 판정 불가한 변환이 그렇다.
    kind: str = ""

    @classmethod
    def from_definition(cls, definition: dict[str, Any]) -> RewriteExample | None:
        bad = (definition.get("bad_sql") or "").strip()
        good = (definition.get("good_sql") or "").strip()
        if not bad or not good:
            return None  # 쌍이 아니면 예시가 아니다
        return cls(
            bad_sql=bad, good_sql=good,
            explanation=(definition.get("explanation") or "").strip(),
            when_regex=(definition.get("when_regex") or "").strip(),
            kind=(definition.get("kind") or "").strip(),
        )

    def applies_to(self, sql: str) -> bool:
        """`when_regex`가 없으면 항상 후보. 있으면 SQL이 그 패턴에 걸릴 때만."""
        if not self.when_regex:
            return True
        try:
            return re.search(self.when_regex, sql, re.I | re.S) is not None
        except re.error:
            logger.warning("canonical_rewrite: when_regex가 잘못된 정규식입니다 — %r", self.when_regex)
            return False

    def as_block(self) -> str:
        lines = [f"고치기 전: {self.bad_sql}", f"고친 뒤: {self.good_sql}"]
        if self.explanation:
            lines.append(f"이유: {self.explanation}")
        return "\n".join(lines)


def load_examples(rule_definitions: list[dict[str, Any]]) -> list[RewriteExample]:
    out = []
    for d in rule_definitions:
        if not isinstance(d, dict):
            logger.warning("canonical_rewrite: definition이 dict가 아니라 %s입니다 — 건너뜁니다", type(d).__name__)
            continue
        ex = RewriteExample.from_definition(d)
        if ex is not None:
            out.append(ex)
    return out


def build_prompt(examples: list[RewriteExample]) -> str:
    blocks = "\n\n".join(e.as_block() for e in examples)
    return (
        "당신은 이미 작성된 PostgreSQL 쿼리의 **형태만** 다듬는 역할입니다. "
        "아래 예시가 보여주는 변환과 같은 상황이면 그대로 적용하고, 해당하지 않으면 "
        "받은 SQL을 **한 글자도 바꾸지 말고** 그대로 돌려주세요.\n\n"
        "반드시 지킬 것: 참조하는 테이블을 바꾸지 마세요. WHERE·HAVING의 값(리터럴)을 "
        "추가·삭제·변경하지 마세요. 새 조건을 만들지 마세요. "
        "바꿔도 되는 것은 SELECT 목록과 컬럼 순서뿐입니다.\n\n"
        "설명 없이 SQL만 출력하세요.\n\n"
        f"[변환 예시]\n{blocks}"
    )


def extract_sql(text: str) -> str:
    """모델 응답에서 SQL만 꺼낸다."""
    body = (text or "").strip()
    m = _FENCE.search(body)
    if m:
        body = m.group(1).strip()
    return body.rstrip(";").strip()


def _invariants(stmt: Any, sql: str) -> tuple[frozenset[str], tuple[str, ...]] | None:
    """(참조 테이블, 거르는 절의 리터럴 **순서열**) — 재작성 전후로 같아야 하는 것들.

    리터럴을 집합이 아니라 **순서 있는 열**로 비교한다. 집합으로 보면
    `city='A' AND county='B'` 를 `city='B' AND county='A'` 로 뒤바꿔도 통과한다 —
    값은 그대로인데 의미가 뒤집히는 변조를 못 잡는다.

    대신 대상은 WHERE·HAVING·조인 조건으로 한정한다. SELECT 목록의 리터럴까지 순서로
    묶으면 **컬럼 순서 변경**(허용해야 하는 축)이 거절돼 버린다.
    """
    if stmt is None or getattr(stmt, "raw_tree", None) is None or not stmt.is_well_formed:
        return None
    from pgxnl.grammar.generated.PostgreSQLParser import PostgreSQLParser as _P
    from pgxnl.parsing.ir_builder import collect_contexts

    tables = set()
    for r in collect_contexts(stmt.raw_tree, _P.Relation_exprContext):
        qn = r.qualified_name() if hasattr(r, "qualified_name") else None
        if qn is not None:
            tables.add(qn.getText().rsplit(".", 1)[-1].strip('"').lower())

    filters: list[tuple[int, str]] = []
    for holder in (_P.Where_clauseContext, _P.Having_clauseContext, _P.Join_qualContext):
        for clause in collect_contexts(stmt.raw_tree, holder):
            for c in collect_contexts(clause, _P.AexprconstContext):
                filters.append((c.start.tokenIndex, c.getText()))
    ordered = tuple(text for _, text in sorted(filters))
    return frozenset(tables), ordered


def verify_rewrite(original: str, rewritten: str, parser: Any) -> tuple[bool, str]:
    """재작성을 받아들여도 되는지. (수용 여부, 사유)를 돌려준다.

    거절 사유를 문자열로 돌려주는 이유는 디버그에 그대로 찍기 위해서다 — 조용히
    원본으로 되돌아가면 재작성 단계가 일하고 있는지 아닌지 알 수 없다.
    """
    if not rewritten:
        return False, "빈 응답"
    if rewritten.strip() == original.strip():
        return False, "변경 없음"

    new_stmt = parser.parse(rewritten)
    if new_stmt is None or not new_stmt.is_well_formed:
        errs = "; ".join(getattr(new_stmt, "syntax_errors", [])[:2]) if new_stmt else ""
        return False, f"문법 오류 {errs}".strip()

    from pgxnl.parsing.base import SqlKind
    if new_stmt.kind != SqlKind.SELECT:
        return False, "SELECT가 아님"

    before = _invariants(parser.parse(original), original)
    after = _invariants(new_stmt, rewritten)
    if before is None or after is None:
        return False, "불변식을 뽑을 수 없음"
    if before[0] != after[0]:
        return False, f"참조 테이블이 바뀜 {sorted(before[0])} -> {sorted(after[0])}"
    if before[1] != after[1]:
        return False, f"거르는 값이 바뀜 {list(before[1])} -> {list(after[1])}"
    return True, "수용"


async def rewrite_sql(
    sql: str, examples: list[RewriteExample], llm: Any, parser: Any,
    *, timeout_seconds: float = 30.0,
) -> tuple[str, str]:
    """예시에 걸리는 SQL을 고친다. LLM이 먼저, 안 되면 코드가 확정한다.

    돌려주는 값은 (최종 SQL, 사유). **수용되지 않으면 — 실패든 무변경이든 — 폴백
    코드가 돈다.** "LLM이 고칠 게 없다고 했다"와 "LLM이 못 했다"를 구분하지 않는
    이유는, 구분해봐야 우리가 확인할 방법이 없기 때문이다. 파서 구현이 있는 변환은
    파서가 최종 판정을 갖는 편이 안전하다.

    폴백까지 없으면 원본을 그대로 돌려준다 — 이 단계가 질의를 막는 일은 없어야 한다.
    """
    import asyncio

    from pgxnl.agent.canonicalize import build_fallback_rule, canonicalize_sql

    applicable = [e for e in examples if e.applies_to(sql)]
    if not applicable:
        return sql, "해당 예시 없음 — 호출 안 함"

    reason = ""
    try:
        resp = await asyncio.wait_for(
            llm.complete(
                system_prompt=build_prompt(applicable),
                messages=[{"role": "user", "content": sql}],
            ),
            timeout=timeout_seconds,
        )
        candidate = extract_sql(getattr(resp, "text", "") or "")
        ok, reason = verify_rewrite(sql, candidate, parser)
        if ok:
            return candidate, f"LLM 수용 — {reason}"
    except TimeoutError:
        reason = f"시간 초과({timeout_seconds}s)"
    except Exception as exc:  # noqa: BLE001 — 재작성 실패가 질의 실패가 되면 안 된다
        logger.warning("canonical_rewrite 호출 실패: %s", exc)
        reason = f"호출 실패 {exc}"

    # LLM이 못 했다 — 파서 구현이 있는 예시들로 코드가 확정한다.
    fallbacks = [r for r in (build_fallback_rule(e.kind) for e in applicable if e.kind) if r]
    if not fallbacks:
        return sql, f"LLM 미수용({reason}), 폴백 없음"
    fixed = canonicalize_sql(sql, parser, fallbacks)
    if fixed == sql:
        return sql, f"LLM 미수용({reason}), 폴백도 변경 없음"
    return fixed, f"LLM 미수용({reason}) — 폴백 {', '.join(type(r).__name__ for r in fallbacks)} 적용"
