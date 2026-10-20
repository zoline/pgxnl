"""생성된 SQL이 **질문을 충실히 따랐는지** 검사한다.

질문 텍스트와 SQL만 대조한다 — 데이터도 스키마도 조회하지 않으므로 비용이 0이고,
데이터가 바뀌어도 낡지 않는다. 프롬프트 규칙으로 지시해도 지켜지지 않는 항목들을
결정론적 코드로 옮기는 것이다(ADR-0009).

두 가지를 본다:

1. **필터 리터럴 변형** — 질문이 `"...for the 2014-2015 academic year?"` 인데 모델이
   `WHERE "Academic Year" = '2014-15'` 를 생성해 0건을 반환했다(27B 12회 연속 재현).
   질문에 정답 문자열이 그대로 있었으므로 데이터를 볼 필요가 없다.
   WHERE/HAVING으로 좁힌 이유: SELECT 절의 문자열(별칭 등)은 질문에 없어도 정상이고,
   evidence·glossary에서 온 코드값(`DOC='52'`, `Virtual='F'`)도 마찬가지다. 그래서
   **"질문에 비슷한 문자열이 있는데 정확히 일치하지 않을 때"만** 신고한다.

2. **SELECT 컬럼 순서** — 질문이 `"Indicate the Street, City, Zip and State."` 인데
   모델이 `SELECT street, city, state, zip` 을 냈다. 평가의 결과 비교가 튜플 위치를
   보므로 순서가 다르면 값이 같아도 오답이다. 프롬프트 규칙 id=22가 같은 내용을
   지시하고 있으나 지켜지지 않는 것이 실측으로 확인됐다.
   **질문에 이름이 그대로 등장하는 컬럼만** 대상으로 한다 — `GSoffered` ↔
   "grade span offered"처럼 표현이 다른 경우까지 순서를 따지면 오탐이 난다.

   (2026-09-07 정정) 이 항목의 초기 사례로 seq 450을 들었으나 방향이 반대였다.
   질문은 `"Street, City, Zip and State"`, evidence는 `"complete address has Street,
   City, State, Zip code"`이고 **gold는 evidence 쪽**이다. 즉 그 문항에서 질문 순서로
   재배열하면 정답을 깨뜨린다 — `ColumnOrderRule`이 충돌 시 손을 떼는 이유가 그것이다.

3. **요구하지 않은 컬럼** — 질문은 한 가지를 묻는데("Which state special schools have
   the highest number of enrollees?") SELECT에 조건 쪽 컬럼까지 들어간다
   (`SELECT school, "Enrollment (K-12)"`, gold는 `School` 하나). 실측상 남은 실패의
   가장 큰 덩어리다. `check_single_column` 참고.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from pgxnl.parsing.ir import PredicateNode, QueryIR

# 작은따옴표 문자열 리터럴('' 이스케이프 포함)
_LITERAL = re.compile(r"'((?:[^']|'')*)'")
# 너무 짧은 리터럴은 우연히 비슷해지기 쉬워 오탐이 난다('F', 'S' 같은 코드값).
_MIN_LENGTH = 4
# 이 이상 비슷하면 "질문의 그 값을 변형한 것"으로 본다. 낮추면 무관한 단어까지 걸린다.
#
# 0.7 -> 0.65 (2026-09-07): `_best_match`가 낱말 중간에서 끊긴 조각을 후보로 삼지 않게
# 고치면서 후보들의 유사도가 전반적으로 내려갔다(`Riverside Unified` ↔ `Riverside`가
# 0.75에서 0.69로). 대신 오탐은 임계값이 아니라 **그 값이 실제로 그 컬럼에 있는지**로
# 거른다 — 호출자가 `column` 필드로 확인한다.
_SIMILARITY_THRESHOLD = 0.65


@dataclass
class LiteralMutation:
    """질문의 값을 변형한 것으로 의심되는 필터 리터럴."""

    literal: str  # SQL에 쓰인 값
    source: str  # 질문에서 찾은 가장 비슷한 문자열
    similarity: float
    # 이 리터럴이 비교된 컬럼 참조(`t1."School Type"`). 호출자가 "그 값이 실제로 그
    # 컬럼에 있는가"를 확인해 오탐을 걸러내는 데 쓴다 — 이 모듈 자체는 데이터를 안 본다.
    column: str | None = None
    # 질문이 따옴표로 묶어 준 값의 **일부만** 썼다(끝의 '!'·'?' 를 뗀 것 등). 질문 안에 그대로 들어 있어
    # 일반 검사로는 통과하던 경우다.
    quoted: bool = False

    def message(self) -> str:
        if self.quoted:
            return (
                f"필터 조건의 '{self.literal}' 은(는) 질문이 따옴표로 준 값 '{self.source}' 의 일부입니다. "
                f"evidence 등 다른 곳의 표기가 달라도 질문의 값을 문장부호까지 그대로 쓰세요."
            )
        return (
            f"필터 조건의 '{self.literal}' 은(는) 질문에 없는 값입니다. "
            f"질문에는 '{self.source}' 라고 되어 있습니다 — 질문의 값을 그대로 쓰세요."
        )


#: 질문이 따옴표로 묶은 값. 앞뒤가 낱말 글자가 아니어야 한다 — `Ancestor's` 의 아포스트로피는 따옴표가 아니다.
_QUOTED = re.compile(r"""(?<!\w)'([^']+?)'(?!\w)|"([^"]+)"|“([^”]+)”""")


def _quoted_values(question: str) -> list[str]:
    return [next(g for g in m.groups() if g) for m in _QUOTED.finditer(question)]


#: 리터럴 바로 앞에 오면 그 리터럴은 **값이 아니라 패턴**이다.
_PATTERN_OP = re.compile(r"(?:I?LIKE|SIMILAR\s+TO)\s*$", re.I)
#: 이스케이프되지 않은 LIKE 와일드카드.
_WILDCARD = re.compile(r"(?<!\\)[%_]")


def _strip_wildcards(literal: str) -> str:
    """`'Riverside%'` -> `'Riverside'`. 질문과 비교할 때 쓰는 형태."""
    return _WILDCARD.sub("", literal).strip()


def _filter_literals(node: PredicateNode | None) -> list[tuple[str, str | None, bool]]:
    """WHERE/HAVING 트리에서 (문자열 리터럴, 비교된 컬럼, 패턴 여부)를 모은다.

    **패턴 여부가 필요한 이유** — `LIKE`의 우변은 값이 아니라 패턴이다. 질문이
    `Riverside`라고 할 때 `LIKE 'Riverside%'`는 올바른 SQL인데, 값으로 비교하면
    "질문에 없는 값"으로 신고된다. 실측(BIRD 444): 모델이 맞게 낸 `LIKE 'Riverside%'`를
    가드가 되돌리게 해 `LIKE 'Riverside'`가 됐고 결과가 **0행**이 됐다
    (실제 값은 `Riverside Unified`, `Riverside County Office of Education`).
    """
    if node is None:
        return []
    out: list[tuple[str, str | None, bool]] = []
    if node.op in ("AND", "OR", "NOT"):
        for child in node.children:
            out.extend(_filter_literals(child))
        return out

    def _scan(text: str, column: str | None) -> None:
        for m in _LITERAL.finditer(text):
            is_pattern = _PATTERN_OP.search(text[: m.start()]) is not None
            out.append((m.group(1), column, is_pattern))

    # CMP는 right에 값이, left에 컬럼이 있다. RAW(IN/LIKE/BETWEEN 등)는 left에 원문
    # 전체가 들어 있어 컬럼을 따로 못 가른다 — 그때는 컬럼을 None으로 둔다.
    if node.right:
        _scan(node.right, (node.left or "").strip() or None)
    if node.left and not node.right:
        _scan(node.left, None)
    return out


def _best_match(literal: str, haystack: str) -> tuple[str, float]:
    """haystack에서 literal과 가장 비슷한 조각과 그 유사도를 찾는다.

    단어 경계에서 시작하는 후보만 본다 — 임의 위치 부분문자열까지 보면 조각난 매칭이
    잡혀 유사도가 부풀려진다.
    """
    best, best_ratio = "", 0.0
    lo, hi = max(1, len(literal) // 2), len(literal) * 2
    for m in re.finditer(r"\S", haystack):
        start = m.start()
        if start and not haystack[start - 1].isspace():
            continue  # 단어 중간에서 시작
        for length in range(lo, hi + 1):
            candidate = haystack[start : start + length]
            if len(candidate) < lo:
                break
            end = start + len(candidate)
            # 끝도 낱말 경계여야 한다. 시작만 보면 낱말 중간에서 잘린 조각이 후보가 되고,
            # 그 조각이 "질문에는 이렇게 되어 있다"며 모델에게 제시된다 — 실측(BIRD 445):
            # "high schools in Monterey"에서 잘라낸 `high schools i` 를 값으로 쓰라고
            # 요구했고, 모델이 따를 수 없어 20회 반복 끝에 타임아웃했다.
            if end < len(haystack) and not haystack[end].isspace() and haystack[end] not in ".,?!":
                continue
            ratio = SequenceMatcher(None, literal.lower(), candidate.lower()).ratio()
            if ratio > best_ratio:
                best, best_ratio = candidate, ratio
    return best.strip(" .,?!"), best_ratio


def check_literals(
    ir: QueryIR, question: str, evidence: str | None = None, quote_source: str | None = None,
) -> list[LiteralMutation]:
    """질문/evidence에 있는 값을 변형한 필터 리터럴을 찾는다. 없으면 빈 리스트.

    `quote_source` 를 주면 따옴표 값은 거기서만 뽑는다(evidence 를 붙이기 전 질문). 안 주면 `question`."""
    quotes = _quoted_values(quote_source if quote_source is not None else question)
    haystack = f"{question} {evidence or ''}"
    lowered = haystack.lower()
    found: list[LiteralMutation] = []
    seen: set[str] = set()

    for literal, column, is_pattern in _filter_literals(ir.where) + _filter_literals(ir.having):
        if len(literal) < _MIN_LENGTH or literal in seen:
            continue
        seen.add(literal)
        # LIKE 패턴은 와일드카드를 뗀 형태로 질문과 맞춰 본다 — 그래야 `Riverside` 를
        # 묻는 질문에 `LIKE 'Riverside%'` 를 쓴 것이 정상으로 판정된다. 뗀 뒤에도
        # 질문에 없으면(`LIKE 'Fresno%'`) 여전히 걸린다.
        needle = _strip_wildcards(literal) if is_pattern else literal
        if not needle or len(needle) < _MIN_LENGTH:
            continue  # 와일드카드뿐인 패턴(`'%'`)은 값이라고 할 게 없다
        if needle.lower() in lowered:
            # 질문에 그대로 있다 — 정상. 단 질문이 따옴표로 묶은 값의 일부만 쓴 경우는 변형이다.
            # 실측(BIRD codebase_community seq 314·316, 2026-10-14): 질문은 'thank you user93!',
            # evidence 는 "thank you user93" — 모델이 evidence 를 따라 '!' 를 떼 0행. 패턴(LIKE)은 일부를
            # 쓰는 게 정상이라 제외. 데이터에 실제로 있는 값이면 호출자(_drop_real_values)가 걸러 준다.
            quoted = [q.lower() for q in quotes]
            # 그 값 자체도 따로 따옴표로 주어졌으면 정상(card_games 359: "Summon - Angel" 과 "Angel").
            if not is_pattern and needle.lower() not in quoted:
                for q in quotes:
                    if needle.lower() in q.lower():
                        found.append(LiteralMutation(
                            literal=literal, source=q, column=column, quoted=True,
                            similarity=round(SequenceMatcher(None, needle.lower(), q.lower()).ratio(), 3),
                        ))
                        break
            continue
        source, ratio = _best_match(needle, haystack)
        # 비슷한 게 아예 없으면 evidence·glossary·스키마에서 온 값일 수 있으므로 넘어간다.
        if ratio >= _SIMILARITY_THRESHOLD and source.lower() != needle.lower():
            found.append(LiteralMutation(
                literal=literal, source=source, similarity=round(ratio, 3), column=column,
            ))
    return found


# --------------------------------------------------------------- SELECT 컬럼 순서

# 별칭·따옴표를 벗기고 컬럼 이름만 남긴다: `t2."School Name"` -> `school name`
_COLUMN_REF = re.compile(r'^(?:[\w"]+\.)?"?([^".]+)"?$')


@dataclass
class ColumnOrderMismatch:
    """질문이 언급한 순서와 SELECT 절의 순서가 다르다."""

    actual: list[str]  # SQL의 순서 (질문에 등장하는 컬럼만)
    expected: list[str]  # 질문에 등장하는 순서

    def message(self) -> str:
        return (
            f"SELECT 절의 컬럼 순서가 질문과 다릅니다. "
            f"질문 순서: {', '.join(self.expected)} / SQL 순서: {', '.join(self.actual)} — "
            f"질문에 언급된 순서대로 반환하세요."
        )


def _plain_column_name(expr: str) -> str | None:
    """SELECT 항목에서 단순 컬럼 참조의 이름만 뽑는다.

    집계·계산식(`count(*)`, `a / b`)은 None을 돌려 순서 판정에서 제외한다 — 질문에
    그대로 등장하지 않는 표현이라 위치를 잴 수 없다.

    공백은 허용한다. QueryIR의 `normalize_expr`가 큰따옴표를 이미 벗기므로
    `T1."School Name"` 은 `t1.school name` 으로 들어오는데, 공백을 이유로 거르면
    공백 있는 컬럼명이 전부 판정에서 빠진다(이 스키마에는 그런 컬럼이 많다).
    어차피 "질문에 그 이름이 그대로 등장하는가"라는 조건이 뒤에서 걸러 준다.
    """
    expr = expr.strip()
    if any(ch in expr for ch in "()+-*/,"):
        return None
    m = _COLUMN_REF.match(expr)
    return m.group(1).strip().lower() if m else None


def check_column_order(ir: QueryIR, question: str) -> ColumnOrderMismatch | None:
    """질문에 이름이 등장하는 컬럼들의 SELECT 순서가 질문 순서와 다르면 신고한다."""
    lowered = question.lower()
    positions: list[tuple[str, int]] = []
    for item in ir.select_items:
        name = _plain_column_name(item.expr)
        if not name:
            continue
        # 단어 경계로 찾아야 'state'가 'estate'에 걸리지 않는다.
        m = re.search(rf"\b{re.escape(name)}\b", lowered)
        if m is None:
            continue  # 질문에 그 이름이 없다 — 순서를 따질 근거가 없다
        positions.append((name, m.start()))

    if len(positions) < 2:
        return None
    order_in_question = [n for n, _ in sorted(positions, key=lambda x: x[1])]
    order_in_sql = [n for n, _ in positions]
    if order_in_sql == order_in_question:
        return None
    return ColumnOrderMismatch(actual=order_in_sql, expected=order_in_question)


# --------------------------------------------------------------- 요구하지 않은 컬럼

#: 요구를 시작하는 표현. 질문에서 "무엇을 달라"가 시작되는 지점을 찾는다.
DEFAULT_ASK_MARKERS = (
    "list", "give", "state", "indicate", "show", "calculate", "what", "which",
    "who", "how many", "how much", "find", "provide", "identify", "name the",
)
#: 조건이 시작되는 표현. 이 앞까지가 "무엇을 달라"는 머리다.
DEFAULT_CONDITION_MARKERS = (
    "with", "whose", "that has", "that have", "that are", "that is", "that were",
    "that was", "which has", "which have", "which are", "which is", "for the",
    "among", "in which", "where", "if ", "having",
)
#: 머리에 이게 있으면 둘 이상을 요구한 것이다.
_MULTI_REQUEST = re.compile(r"\band\b|,|\balong with\b|\bas well as\b|\btogether with\b", re.IGNORECASE)

#: SQL 식별자에서 컬럼 후보를 뽑을 때 무시할 예약어/별칭.
_SQL_NOISE = frozenset(["select", "from", "where", "and", "or", "as", "on", "inner", "join", "left", "right", "outer", "full", "cross", "group", "by", "order", "having", "limit", "offset", "desc", "asc", "nulls", "first", "last", "cast", "real", "integer", "numeric", "text", "nullif", "coalesce", "count", "sum", "avg", "max", "min", "distinct", "not", "null", "is", "in", "between", "like", "ilike", "case", "when", "then", "else", "end", "over", "rank", "dense_rank", "row_number", "partition", "extract", "year", "month", "day", "interval", "true", "false"])


@dataclass
class UnrequestedColumn:
    """질문은 한 가지를 요구했는데 SELECT에 더 들어 있다."""

    extra: list[str]  # 여분으로 판단한 SELECT 항목들
    kept: str  # 답으로 본 항목
    head: str  # 질문에서 요구로 읽은 부분

    def message(self) -> str:
        return (
            f"질문은 '{self.head.strip()}' 한 가지를 요구했는데 SELECT에 "
            f"{', '.join(self.extra)} 이(가) 더 있습니다 — 조건에 쓴 컬럼을 결과에도 "
            f"넣은 것은 아닌지 다시 판단하세요. 필요 없다면 {self.kept} 만 남기세요."
        )


def _request_head(
    question: str, ask_markers: tuple[str, ...], condition_markers: tuple[str, ...],
) -> str | None:
    """질문에서 "무엇을 달라"에 해당하는 부분만 잘라낸다. 판단 불가면 None.

    요구 동사부터 그 **뒤** 첫 조건 표지까지다. 조건이 앞에 오는 질문("For patients with
    severe thrombosis, list their ID, sex and disease")에서 앞쪽 `with`를 경계로 잡으면
    머리가 "For patients"가 되어 등위 접속을 놓친다 — 실측으로 확인해 요구 동사 기준으로
    바꿨다(정밀도 88.1% -> 92.3%).

    요구 문장이 둘 이상이면 None을 돌려 판단을 보류한다. "What is X? How much had Y?"
    같은 질문은 gold도 여러 컬럼이라, 한 절만 보고 판정하면 오탐이 된다.
    """
    parts = [s.strip() for s in re.split(r"[?.]\s+|\?$|\.$", question) if s.strip()]
    ask_re = re.compile(r"\b(" + "|".join(re.escape(m) for m in ask_markers) + r")\b", re.IGNORECASE)
    if len([s for s in parts if ask_re.search(s)]) > 1:
        return None

    q = question.strip()
    m = ask_re.search(q)
    rest = q[m.start():] if m else q
    cond_re = re.compile(r"\b(" + "|".join(re.escape(c) for c in condition_markers) + r")\b", re.IGNORECASE)
    c = cond_re.search(rest)
    return rest[: c.start()] if c else rest


def _identifiers(text: str) -> set[str]:
    """SQL 조각에서 컬럼 후보 이름을 뽑는다(예약어·별칭 제외)."""
    out: set[str] = set()
    for quoted, bare in re.findall(r'(?:"([^"]+)"|\b([A-Za-z_][A-Za-z0-9_]*)\b)', text or ""):
        name = (quoted or bare).lower()
        if not name or name in _SQL_NOISE or re.fullmatch(r"t\d+", name):
            continue
        out.add(name)
    return out


def check_single_column(
    ir: QueryIR, question: str, *, strict: bool = True,
    ask_markers: tuple[str, ...] = DEFAULT_ASK_MARKERS,
    condition_markers: tuple[str, ...] = DEFAULT_CONDITION_MARKERS,
) -> UnrequestedColumn | None:
    """질문이 한 가지만 요구했는데 SELECT가 여러 개면 신고한다. 아니면 None.

    500문항 전수 측정(2026-09-07) — gold SQL에 경고가 달리는 비율로 잰 안전성:

        느슨(strict=False)  335건 발동, gold 오탐 24건  -> 정밀도 92.8%
        엄격(strict=True)   335건 발동, gold 오탐  7건  -> 정밀도 97.9%

    엄격 모드는 **여분 컬럼이 WHERE/ORDER BY/GROUP BY에도 등장할 때만** 신고한다.
    "조건에 쓴 컬럼이 결과로 새어 나왔다"는 것이 원래 실패 양상이기 때문이다. 느슨
    모드의 오탐은 대부분 한 개념이 여러 컬럼인 경우인데(`full name` -> first_name +
    last_name, `coordinates` -> lat + lng), 그런 컬럼은 조건절에 안 나오므로 엄격
    모드에서 걸러진다.

    겹침 신호 하나만으로는 정밀도가 57%였다(docs 기록) — 질문 신호와 함께 봐야 한다.

    **컬럼을 지우지 않는다.** 관찰만 돌려주고 모델이 판단한다. 모델은 스키마를 이미
    봤으므로 "full name은 두 컬럼이어야 한다" 같은 건 알고 있고, 코드가 지웠다면 남은
    오탐이 전부 새 오답이 됐을 것이다.
    """
    if len(ir.select_items) < 2:
        return None
    head = _request_head(question, ask_markers, condition_markers)
    if head is None or _MULTI_REQUEST.search(head):
        return None  # 요구가 둘 이상이거나 판단 불가

    kept, extras = ir.select_items[0], ir.select_items[1:]
    if strict:
        tail = ir.where.signature() if ir.where else ""
        tail += " ".join(expr for expr, _ in ir.order_by) + " " + " ".join(ir.group_by)
        tail += ir.having.signature() if ir.having else ""
        tail_names = _identifiers(tail)
        extras = [e for e in extras if _identifiers(e.expr) & tail_names]
        if not extras:
            return None
    return UnrequestedColumn(
        extra=[e.expr.strip() for e in extras], kept=kept.expr.strip(), head=head,
    )
