"""SELECT 항목 ↔ 질문 구절 대응 (§question_guard 4).

"질문이 요구하지 않은 컬럼이 결과에 있다"는 오늘까지 가장 자주 나온 실패 유형이다
(BIRD 448·456·467). 기존 `single_column` 가드(규칙 30)는 **개수만** 본다 — "질문이 하나만
요구했는데 SELECT가 여럿"까지 말하고 어느 것이 군더더기인지는 못 짚어, 정밀도 97.9%에도
EX 기여가 0이었다. 여기서는 항목마다 근거 구절을 받아 **지목**한다.

판정은 LLM이 한다(호출 1회). 그래서 결정론적 교정이 아니라 **조언**이다 — 코드가 컬럼을
지우면 조용한 오답이 될 수 있다(ADR-0009 "모호하면 손대지 않는다").

측정(2026-09-09, gold 30문항):
  - 정밀도: gold SELECT 항목 56개 중 오탐 **0건**
  - 재현율: 컬럼 수가 gold와 다른 3건 중 1건 포착(448의 `"School Name"`)
    · 456은 놓친다 — 질문에 `number of enrollees`가 있어 모델이 REQUESTED로 볼 근거가 있다
    · 467은 범위 밖 — 컬럼이 **모자란** 경우다
"""
from __future__ import annotations

from dataclasses import dataclass

#: 항목별 근거를 받는 프롬프트. 디버그 출력과 가드가 **같은 문구**를 쓴다 — 따로 두면
#: 한쪽만 고쳐져 "디버그에는 보이는데 가드는 안 잡는" 상태가 된다.
#: 이 가드의 LLM 호출 상한(초). 조언용이라 늦으면 **그냥 건너뛴다** — 실측(BIRD 448)에서
#: 이 호출이 클라이언트 상한 180초를 다 쓰고 실패했고, 그 180초가 ReAct 벽시계
#: 상한(agent_max_seconds=300)을 잡아먹어 질의가 SQL 없이 끝났다. 정상 호출은 3~8초다.
RATIONALE_TIMEOUT_SECONDS = 25.0

RATIONALE_PROMPT = (
    "다음 질문에 답하려고 작성된 SQL이 있습니다. SELECT 절의 각 항목이 질문의 "
    "어느 부분 때문에 필요한지 밝히세요.\n\n"
    "항목마다 정확히 한 줄로, 아래 형식으로만 답하세요:\n"
    "<SELECT 항목> | <질문에서 그대로 옮긴 구절> | REQUESTED 또는 CONDITION\n\n"
    "- 두 번째 칸은 질문 원문에서 **글자 그대로** 복사하세요. 바꿔 쓰거나 "
    "지어내지 마세요.\n"
    "- REQUESTED: 질문이 그 값을 결과로 달라고 한 경우\n"
    "- CONDITION: 질문이 그 값을 조건·기준으로만 언급한 경우\n"
    "- 근거가 질문에 없으면 두 번째 칸에 NONE, 세 번째 칸에 CONDITION을 쓰세요.\n"
    "- 설명, 머리말, 코드블록은 쓰지 마세요."
)


@dataclass(frozen=True)
class RationaleRow:
    """모델이 돌려준 한 줄. `quote_found`는 인용이 질문 원문에 실제로 있는지."""

    item: str
    quote: str
    kind: str
    quote_found: bool

    @property
    def is_requested(self) -> bool:
        return self.kind == "REQUESTED"

    @property
    def has_basis(self) -> bool:
        """근거가 있다고 볼 수 있는가 — NONE도 아니고 지어낸 인용도 아니다."""
        return self.quote.upper() != "NONE" and self.quote_found

    def debug_line(self) -> str:
        if self.quote.upper() == "NONE":
            mark = "✗ 질문에 근거 없음"
        elif self.quote_found:
            mark = "✓"
        else:
            mark = "✗ 원문에 없음(지어낸 인용)"
        return f'    {self.item}  ←  "{self.quote}"  [{self.kind}] {mark}'


def parse_rationale(text: str, question: str) -> list[RationaleRow]:
    """모델 응답을 행으로 파싱한다. 형식을 안 지킨 줄은 버린다."""
    lowered = question.lower()
    rows: list[RationaleRow] = []
    for line in (text or "").splitlines():
        if "|" not in line:
            continue
        parts = [c.strip() for c in line.split("|")]
        if len(parts) < 3:
            continue
        item, quote, kind = parts[0], parts[1], parts[2].upper()
        # 모델이 "REQUESTED (설명)"처럼 덧붙이는 경우가 있어 포함 여부로 본다.
        kind = "REQUESTED" if "REQUESTED" in kind else ("CONDITION" if "CONDITION" in kind else kind)
        rows.append(RationaleRow(item, quote, kind, quote.lower() in lowered))
    return rows


@dataclass(frozen=True)
class UnsupportedColumns:
    """질문에 근거가 없는 SELECT 항목들."""

    items: tuple[str, ...]

    def message(self) -> str:
        cols = ", ".join(self.items)
        return (
            f"SELECT의 {cols} 은(는) 질문이 결과로 요구한 값이 아닙니다 — 질문이 그 값을 "
            "달라고 한 구절을 찾을 수 없습니다. 질문이 요구한 항목만 남기고 다시 작성하세요. "
            "그 컬럼이 정말 필요하다고 판단하면 같은 SQL을 다시 보내면 됩니다."
        )


def find_unsupported(rows: list[RationaleRow], *, select_count: int) -> UnsupportedColumns | None:
    """근거 없는 항목을 고른다. 없으면 None.

    안전장치 둘:
      - 모델이 항목 수를 못 맞추면(형식 불일치) 판단을 포기한다 — 어느 항목을 말하는지
        신뢰할 수 없다.
      - 모든 항목이 근거 없다고 나오면 포기한다. 그 SQL을 통째로 부정하는 셈이라
        조언이 될 수 없고, 질문 해석 자체가 어긋난 경우다.
    """
    if select_count <= 0 or len(rows) != select_count:
        return None
    bad = tuple(r.item for r in rows if not (r.is_requested and r.has_basis))
    if not bad or len(bad) == len(rows):
        return None
    return UnsupportedColumns(bad)
