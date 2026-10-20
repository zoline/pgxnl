"""필터에 기여하지 않는 조인 감지 (§question_guard 5).

BIRD 443에서 실측: 모델이 `schools`를 조인해 놓고 WHERE에서 한 번도 쓰지 않고,
오직 학교 이름을 `frpm."School Name"` 대신 `schools.school`에서 가져오려고 붙였다.

```
gold  SELECT T2."School Name" FROM satscores T1 JOIN frpm T2 ...
pred  SELECT T3.school FROM frpm T1 JOIN satscores T2 ... JOIN schools T3 ON T1.cdscode = T3.cdscode
                                                          └─ 조건에 한 번도 안 쓰임
```

두 컬럼은 같은 개념의 **사본**이고 9,941행 중 207행(2.1%)이 다르다 — 어느 쪽을 쓰느냐로
답이 갈린다. 조인을 추가하지 않았다면 애초에 사본을 쓸 수밖에 없었을 것이다.

**조언만 한다.** 조인을 코드가 지우면 안 된다 — INNER JOIN은 매칭 없는 행을 걸러내고
1:N이면 행을 늘리므로, "안 쓰는 조인"처럼 보여도 실제로는 필터다. 443은 조인 키가
`schools`의 PK라 안전하지만 일반적으로 보장되지 않는다(ADR-0009 "모호하면 손대지 않는다").
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def _quote(name: str) -> str:
    """PostgreSQL이 소문자로 접지 않도록, 필요한 경우에만 큰따옴표를 붙인다."""
    return name if re.fullmatch(r"[a-z_][a-z0-9_$]*", name) else f'"{name}"'


@dataclass(frozen=True)
class RedundantJoin:
    """SELECT에서만 쓰이는 조인과, 그 컬럼을 대신할 수 있는 이미 조인된 사본."""

    alias: str
    table: str
    column: str
    replacement_table: str
    replacement_column: str
    replacement_alias: str

    def message(self) -> str:
        return (
            f"{self.table}({self.alias})을(를) 조인했지만 조건에는 쓰지 않고 "
            f"{self.alias}.{self.column} 을 결과에 넣으려고만 씁니다. 같은 값이 이미 조인된 "
            f"{self.replacement_table}에도 {_quote(self.replacement_column)} 으로 있습니다 — "
            f"조인을 빼고 {self.replacement_alias}.{_quote(self.replacement_column)} 을 쓰는 것이 "
            f"질문에 더 맞는지 다시 판단하세요. 두 컬럼은 값이 일부 행에서 다릅니다."
        )


def _aliases_in(text: str) -> set[str]:
    """`별칭.컬럼` 형태에서 별칭만 뽑는다. 따옴표 컬럼(`t1."School Name"`)도 포함한다."""
    return {m.lower() for m in re.findall(r'\b([A-Za-z_][\w$]*)\s*\.', text or "")}


def _predicate_text(node) -> str:
    if node is None:
        return ""
    parts = [node.left or "", node.right or ""]
    for child in getattr(node, "children", []) or []:
        parts.append(_predicate_text(child))
    return " ".join(p for p in parts if p)


def find_redundant_joins(
    ir, *, alias_to_table: dict[str, str], copies: dict[tuple[str, str], tuple[str, str]],
) -> list[RedundantJoin]:
    """조인했으나 SELECT에서만 쓰이고, 그 컬럼의 사본이 이미 조인된 테이블에 있는 경우.

    `copies`는 `CanonicalColumnRule`이 쓰는 것과 같은 맵이다: (사본테이블, 사본컬럼) ->
    (정본테이블, 정본컬럼). 여기서는 **역방향**으로도 본다 — 질문에 따라 어느 쪽이 맞는지는
    모델이 정한다. 우리는 "조인을 새로 만들면서까지 갈아탈 이유가 있는가"만 묻는다.
    """
    if ir is None or not ir.joins or ir.has_subquery:
        return []

    # SELECT 밖에서 쓰인 별칭. **조인 자신의 ON은 세지 않는다** — 조인해 온 테이블의
    # 별칭은 그 ON에 반드시 나오므로, 세면 아무것도 걸리지 않는다. 다른 조인의 ON에
    # 나오는 것은 진짜 사용이다(조인 체인의 중간 고리라 뺄 수 없다).
    used_outside = _aliases_in(_predicate_text(getattr(ir, "where", None)))
    used_outside |= _aliases_in(_predicate_text(getattr(ir, "having", None)))
    used_outside |= _aliases_in(" ".join(ir.group_by or []))
    used_outside |= _aliases_in(" ".join(e for e, _ in (ir.order_by or [])))
    on_aliases: list[set[str]] = [_aliases_in(_predicate_text(j.on)) for j in ir.joins]

    # (테이블, 컬럼) -> 그 테이블에 붙은 별칭. 사본 대체 후보를 찾는 데 쓴다.
    table_alias = {t: a for a, t in alias_to_table.items() if a != t}
    joined = {alias_to_table.get(a) for a in table_alias}

    # 사본 맵은 소문자로 정규화돼 들어온다. 역방향도 넣되, 메시지에 쓸 컬럼명은
    # 인용이 필요할 수 있으므로(`"School Name"`) 원형을 잃지 않게 그대로 보관한다.
    pairs: dict[tuple[str, str], tuple[str, str]] = {}
    for (t, c), (ct, cc) in copies.items():
        pairs[(t.lower(), c.lower())] = (ct, cc)
        pairs[(ct.lower(), cc.lower())] = (t, c)

    out: list[RedundantJoin] = []
    seen: set[str] = set()
    for item in ir.select_items:
        for alias, column in re.findall(r'\b([A-Za-z_][\w$]*)\s*\.\s*("[^"]+"|[\w$]+)', item.expr or ""):
            a = alias.lower()
            if a in used_outside or a in seen:
                continue
            table = alias_to_table.get(a)
            if table is None or table == a:
                continue
            # 이 별칭이 조인으로 들어온 것인지(FROM 첫 테이블이면 뺄 수 없다)
            own = [i for i, j in enumerate(ir.joins) if j.table.lower() == table.lower()]
            if not own:
                continue
            # 자기 조인 외의 ON에 나오면 조인 체인의 고리라 뺄 수 없다
            if any(a in on for i, on in enumerate(on_aliases) if i not in own):
                continue
            col = column.strip('"').lower()
            target = pairs.get((table.lower(), col))
            if target is None:
                continue
            rt, rc = target
            if rt.lower() not in {t.lower() for t in joined if t}:
                continue  # 대체할 테이블이 이 질의에 없다 — 다른 조인을 만들라고 할 수는 없다
            ra = table_alias.get(rt.lower())
            if not ra:
                continue
            seen.add(a)
            out.append(RedundantJoin(a, table, column.strip('"'), rt, rc, ra))
    return out
