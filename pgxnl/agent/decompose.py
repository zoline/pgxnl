"""질문을 "요구(OUTPUT)"와 "조건(FILTER)"으로 분해한다. design 문서 §5.2 관련.

**왜 생성 전에 묻는가** — 사후 설명은 편향돼 있다. 이미 쓴 SQL을 보여주고 각 컬럼의
근거를 대라고 하면 모델이 자기 답을 정당화하는 쪽으로 기운다(실측 BIRD 443:
`numge1500`을 SELECT에 넣은 뒤 설명을 시키면 `REQUESTED`라고 답했지만, SQL 없이 질문만
주고 분해시키면 `FILTER`로 분류했다). 그래서 SQL을 쓰기 전에, 방어할 답이 없는 상태에서
묻는다.

**판정에 쓰지 않는다.** 생성 단계에 참고 자료로 넘길 뿐이다. 30문항 실측에서 분해 자체는
대체로 맞았지만 두 가지 한계가 있었다:

1. 자연어 개념 하나가 스키마에서 여러 컬럼이 된다("full communication address" ->
   Street/City/State/Zip). 분해는 스키마 링킹 이전이라 이를 알 수 없으므로, 항목 수를
   SELECT 컬럼 수와 대조해 판정하면 안 된다.
2. 요구 문장이 둘 이상이면 형식이 무너져 질문 전체를 그대로 복사한다(30문항 중 2건).

둘 다 "참고 자료로만 쓴다"면 무해하다 — 1은 모델이 스키마를 보고 알아서 펴고, 2는
원문 복사본이 하나 더 붙을 뿐이다. 판정 근거로 삼는 순간 둘 다 오답의 원인이 된다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pgxnl.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)

_PROMPT = (
    "데이터베이스에 물어볼 질문이 주어집니다. 이 질문을 두 부분으로 나누세요.\n\n"
    "OUTPUT: 질문이 **결과로 돌려달라고 한** 것\n"
    "FILTER: 질문이 **대상을 좁히는 조건**으로만 쓴 것\n\n"
    "각 항목을 한 줄씩, 아래 형식으로만 쓰세요:\n"
    "OUTPUT | <질문에서 그대로 옮긴 구절>\n"
    "FILTER | <질문에서 그대로 옮긴 구절>\n\n"
    "규칙:\n"
    "- 두 번째 칸은 질문 원문에서 **글자 그대로** 복사하세요.\n"
    "- 조건에 쓰인 값이라고 해서 결과로 돌려주는 것은 아닙니다. 질문이 명시적으로 "
    "달라고 한 것만 OUTPUT입니다.\n"
    "- SQL을 쓰지 마세요. 설명, 머리말, 코드블록도 쓰지 마세요."
)

#: 인용이 이 길이를 넘으면 "질문을 통째로 복사"한 것으로 본다(형식 붕괴). 비율로 재는
#: 이유는 질문 길이가 제각각이기 때문이다.
_WHOLE_QUESTION_RATIO = 0.8


@dataclass
class Decomposition:
    outputs: list[str] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """생성 단계에 넘길 만한가. OUTPUT이 하나도 없으면 넘길 내용이 없다."""
        return bool(self.outputs)

    def as_prompt_block(self) -> str:
        lines = [f"- 결과로 요구된 것: {o}" for o in self.outputs]
        lines += [f"- 조건으로만 언급된 것: {f}" for f in self.filters]
        return "\n".join(lines)


def parse_response(text: str, question: str) -> Decomposition:
    """모델 응답을 파싱하고 인용을 검증한다.

    질문 원문에 없는 인용은 버린다 — 지어낸 근거를 생성 단계로 흘려보내면 존재하지 않는
    요구를 만들어낸다. 질문을 통째로 복사한 항목도 버린다(분해가 안 된 것이라 정보가 없고,
    그대로 넘기면 질문이 두 번 들어간다).
    """
    lowered = question.lower()
    out = Decomposition()
    for raw in (text or "").splitlines():
        if "|" not in raw:
            continue
        kind, _, quote = raw.partition("|")
        kind, quote = kind.strip().upper(), quote.strip()
        if kind not in ("OUTPUT", "FILTER") or not quote:
            continue
        if quote.lower() not in lowered:
            continue  # 지어낸 인용
        if len(quote) >= len(question) * _WHOLE_QUESTION_RATIO:
            continue  # 질문 통째 복사 — 분해가 안 됐다
        (out.outputs if kind == "OUTPUT" else out.filters).append(quote)
    # 같은 구절이 양쪽에 오면 분해가 모순이다 — 그 항목은 버린다.
    both = {o.lower() for o in out.outputs} & {f.lower() for f in out.filters}
    if both:
        out.outputs = [o for o in out.outputs if o.lower() not in both]
        out.filters = [f for f in out.filters if f.lower() not in both]
    return out


async def decompose_question(
    llm: BaseLLMClient, question: str, evidence: str | None = None,
) -> tuple[Decomposition, dict | None]:
    """(분해 결과, 토큰 사용량). 실패하면 빈 분해를 돌려준다 — 보조 단계다."""
    user = f"[질문]\n{question}"
    if evidence:
        user += f"\n\n[참고 정보]\n{evidence}"
    try:
        resp = await llm.complete(system_prompt=_PROMPT, messages=[{"role": "user", "content": user}])
    except Exception:  # 보조 단계가 필수 경로를 막으면 안 된다
        logger.warning("질문 분해 실패, 건너뜁니다", exc_info=True)
        return Decomposition(), None
    return parse_response(resp.text or "", question), resp.usage
