"""질문 보강. design 문서 §5.2 참고.

스키마 링킹 이전에 실행되는 경량 전처리. 모호성을 감지하고, API 기반 서비스 특성상
1차 구현은 비대화형 재작성만 제공한다 (대화형 명확화 질문은 SSE 스트리밍과의 통합
설계가 추가로 필요해 이후 단계로 미룬다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pgxnl.llm.base import BaseLLMClient

#: 조건절이 시작되는 표지. 이 뒤부터 문장 끝까지가 "조건"이다.
#: `along with`/`together with`의 `with`는 제외한다 — 그건 조건이 아니라 **추가 요구**를
#: 잇는 말이라, 묶으면 gold가 요구한 컬럼을 조건으로 만들어버린다(실측 seq 204:
#: "Name the races along with its circuit name and location", gold 3컬럼).
_CONDITION_HEAD = re.compile(
    r"(?<!along )(?<!together )\b(with|whose|that (?:has|have|are|is|were|was))\b",
    re.IGNORECASE)
#: 조건 구간 **안에** 이게 있으면 그건 조건이 아니라 두 번째 요구다(실측 seq 71의
#: "and include its department and college name", seq 133의 "and how many matches were
#: played"). 둘 다 gold가 여러 컬럼을 낸다.
_REQUEST_INSIDE = re.compile(
    r"\b(include|list|show|give|name|display|return|how many|how much|"
    r"along with|as well as|together with)\b", re.IGNORECASE)
#: 요구 동사 — 조건 표지를 이 **뒤**에서 찾아야 한다. "For patients with X, list Y" 처럼
#: 조건이 앞에 오면 앞쪽 `with`를 경계로 잡아 엉뚱한 데를 묶는다.
_ASK_VERB = re.compile(
    r"\b(list|give|state|indicate|show|calculate|what|which|who|how many|how much|"
    r"find|provide|identify|name the)\b", re.IGNORECASE)
#: 문장 끝의 물음표·마침표(와 그 앞 공백)
_SENTENCE_TAIL = re.compile(r"\s*[?.]\s*$")

#: "없을 수도 있다"는 표지. 이 표지가 붙은 요구는 값이 없어도 앞 요구의 행을 살려야 한다.
_OPTIONAL_MARK = re.compile(r"\bif (?:there (?:is|are) )?any\b|\bif available\b", re.IGNORECASE)
#: 한 문장 안에서 두 번째 요구가 시작되는 자리: ", and find", " and list", "Also, list" 등.
_SECOND_REQUEST = re.compile(
    r",?\s+(?:and\s+(?:also\s+)?|also,?\s+)(?=(?:find|list|show|give|state|indicate|provide|identify|name)\b)",
    re.IGNORECASE)

_AMBIGUOUS_DATE_PATTERNS = [
    re.compile(r"\b(최근|요즘|이번)\b"),
    re.compile(r"\b(recent|latest|this (month|quarter|year))\b", re.IGNORECASE),
]

@dataclass
class AmbiguitySignal:
    found: bool
    reasons: list[str]


@dataclass
class EnrichedQuestion:
    text: str
    rewritten: bool
    original: str | None = None
    reasons: list[str] | None = None
    # 이 호출 동안 실제로 발생한 LLM 호출들의 토큰 사용량 — 디버그 표시용(§토큰 디버그).
    token_usage: list[dict[str, int]] | None = None
    # 모호성 판단/재작성에 실제로 보낸 프롬프트와 응답 — 디버그 표시용(사용자 요청:
    # "모호성판단 관련해서 debug에서 prompt들을 보여달라"). [{"call": "enrich_detect"|
    # "enrich_rewrite", "prompt": ..., "response": ...}, ...]
    debug_log: list[dict[str, str]] | None = None


class QuestionEnricher:
    """모호성 판단(엄격한 2줄 포맷 분류)과 재작성(자유 텍스트 생성)은 성격이 달라
    (§5.2 로드맵상 stage 분리 검토 항목) 각각 다른 LLM 프로필을 지정할 수 있도록
    별도 클라이언트로 주입받는다. `enrich_detect`/`enrich_rewrite` 단계에 대응한다
    (api/llm_profiles.py의 STAGES 참고)."""

    def __init__(
        self, detect_llm: BaseLLMClient, rewrite_llm: BaseLLMClient, *,
        enabled: bool, semantic_check_enabled: bool = False,
    ) -> None:
        self._detect_llm = detect_llm
        self._rewrite_llm = rewrite_llm
        self._enabled = enabled
        self._semantic_check_enabled = semantic_check_enabled
        # enrich() 호출마다 리셋되는 임시 누적 버퍼 — 이 인스턴스는 orchestrator 하나당
        # 한 번 만들어져 여러 요청에 재사용되므로 self에 영구 누적하면 안 된다.
        self._last_usage: list[dict[str, int]] = []
        self._last_debug: list[dict[str, str]] = []

    async def enrich(
        self, question: str, *, evidence: str | None = None, domain_hint: str | None = None,
    ) -> EnrichedQuestion:
        """domain_hint: glossary_store에서 미리 골라 온 도메인 지식(예: "average score in
        writing"이 이미 avgscrwrite 컬럼을 가리킨다는 정의) — enrichment는 스키마 링킹
        이전이라 원래 스키마를 전혀 모르는데(§5.2 설계), 그 때문에 "이미 존재하는
        컬럼"을 "새로 계산해야 할 집계"로 오판해 불필요한 재작성을 하고, 그 재작성이
        SQL 생성에 실제로 없는 집계 컬럼을 추가시키는 사례를 실측으로 확인했다
        (orchestrator가 glossary_store.for_enrichment()로 조회해서 넘겨준다 — 이
        클래스 자체는 glossary_store를 직접 모른다, DB 의존성을 안 늘리기 위함)."""
        self._last_usage = []
        self._last_debug = []
        if not self._enabled:
            return EnrichedQuestion(text=question, rewritten=False)

        # evidence가 있으면 모호성 판단에도 같이 보여준다. evidence 없이 question만
        # 보고 판단하면, evidence가 이미 해소해주는 모호함(예: "valid charter number"
        # 정의)까지 "모호하다"고 걸려 불필요하게 재작성이 발동하는 걸 실측으로 확인했다
        # — 재작성 자체가 SQL 컬럼 구성/순서에 변동성을 더하는 부작용이 있어, evidence로
        # 이미 풀리는 모호함은 애초에 재작성 대상에서 빼는 게 낫다. domain_hint도 같은
        # 이유로 판단에 같이 보여준다. 재작성의 출력 대상(다시 쓰는 텍스트)은 여전히
        # question만이다(evidence는 orchestrator가 재작성 이후 별도로 다시 붙인다) —
        # 다만 _rewrite()에는 evidence/domain_hint를 참고 자료로 같이 넘긴다. evidence가
        # 이미 정밀하게 정의한 계산식/조건(예: "sum(평균)/count(학교수)")이 있는데도 재작성이
        # 그 뉘앙스를 무시하고 더 단순한(부정확한) 표현으로 뭉개버리는 사례를 실측으로
        # 확인했기 때문이다 — evidence를 "보되 출력엔 안 섞는" 것과 "아예 안 보는" 것은
        # 다른 문제다.
        #
        # 이어붙이는 형식도 중요하다는 걸 실측으로 확인했다: "질문\n\n[참고 정보]\n증거"처럼
        # 구조적으로 분리하면, 모델이 "[참고 정보]"를 뺀 순수 질문 부분만 다시 놓고
        # evidence와 무관한 별개의 모호함까지 찾아내 재작성을 더 자주 발동시켰다(3번 중
        # 2번). 반면 한 문장처럼 자연스럽게 이어붙이면 훨씬 안정적으로 재작성이 불필요
        # 하다고 판단했다(3번 중 3번) — 사용자가 실제로 이렇게 자연스럽게 이어 써서
        # 질문하는 걸 관찰하고 재현한 것이다.
        check_text = question
        if evidence:
            check_text += f" {evidence}"
        if domain_hint:
            check_text += f" {domain_hint}"

        # 조건절 경계 표시 — LLM을 타지 않는 결정론적 단계라 모호성 판단보다 먼저 한다.
        # 여기서 경계가 잡히면 그 자체로 모호함이 해소되므로 재작성을 부를 이유가 없다
        # (재작성은 SQL 컬럼 구성·순서를 흔든다 — §_rewrite 주석).
        bracketed, bracket_reason = self._bracket_conditions(question)
        annotated, annotate_reason = self._annotate_requests(bracketed)
        if annotate_reason:
            bracketed = annotated
            bracket_reason = "; ".join(r for r in (bracket_reason, annotate_reason) if r)

        ambiguity = self._detect_pattern_ambiguity(check_text)
        if not ambiguity.found and self._semantic_check_enabled:
            ambiguity = await self._detect_semantic_ambiguity(check_text)
        if not ambiguity.found:
            return EnrichedQuestion(
                text=bracketed, rewritten=bracket_reason is not None,
                original=question if bracket_reason else None,
                reasons=[bracket_reason] if bracket_reason else None,
                token_usage=self._last_usage, debug_log=self._last_debug,
            )

        # 재작성 대상은 괄호를 친 텍스트다 — 경계 정보를 재작성 LLM도 보게 한다.
        rewritten = await self._rewrite(bracketed, ambiguity, evidence=evidence, domain_hint=domain_hint)
        reasons = ([bracket_reason] if bracket_reason else []) + list(ambiguity.reasons)
        return EnrichedQuestion(
            text=rewritten, rewritten=True, original=question, reasons=reasons,
            token_usage=self._last_usage, debug_log=self._last_debug,
        )

    def _bracket_conditions(self, question: str) -> tuple[str, str | None]:
        """조건절이 어디서 끝나는지 괄호로 표시한다. 원문 글자는 하나도 바꾸지 않는다.

        `"Give the names of the schools with A and B?"` 에서 `and B`가 **두 번째 요구
        항목**인지 **두 번째 조건**인지 문장 구조만으로는 결정되지 않는다. 실측(BIRD 443):
        모델은 일관되게 "요구"로 읽어 `B`를 SELECT에 넣었고, gold는 조건으로 읽었다.
        용어집 scope를 enrich/disabled/both로 바꿔봐도 셋 다 그대로였다 — 용어 정의의
        문제가 아니라 문장 경계의 문제다.

        `with (A and B)?` 로 묶어주자 SELECT에서 빠지고 조건절도 gold와 같아졌다.

        LLM을 타지 않는다. 자유 재작성은 evidence의 계산식을 뭉개고 SQL 컬럼 구성·순서를
        흔드는 것이 실측으로 확인됐는데(§_rewrite 주석), 괄호는 **경계만 표시**하므로 그
        위험이 없다.

        붙이지 않는 경우:
        1. 조건부에 등위 접속(`and`/`or`)이 없다 — 묶을 이유가 없다
        2. 이미 괄호가 있다 — 사람이 의도한 묶음을 덮어쓰면 안 된다
        3. 요구 문장이 둘 이상이다 — 어느 문장의 조건인지 정할 수 없다
        4. 조건 표지가 요구 동사보다 앞에 있다 — 경계를 잘못 잡는다
        5. 조건 구간 안에 요구 동사가 있다 — 그건 조건이 아니라 두 번째 요구다
        """
        q = question.strip()
        if "(" in q or ")" in q:
            return question, None
        if len([s for s in re.split(r"[?.]\s+|\?$|\.$", q) if s.strip() and _ASK_VERB.search(s)]) > 1:
            return question, None
        ask = _ASK_VERB.search(q)
        head = _CONDITION_HEAD.search(q, ask.end() if ask else 0)
        if head is None:
            return question, None
        tail = _SENTENCE_TAIL.search(q)
        end = tail.start() if tail else len(q)
        body = q[head.end():end]
        if not body.strip() or not re.search(r"\b(and|or)\b", body, re.IGNORECASE):
            return question, None
        if _REQUEST_INSIDE.search(body):
            return question, None  # 조건이 아니라 두 번째 요구다
        bracketed = f"{q[:head.end()]} ({body.strip()}){q[end:]}"
        return bracketed, "조건절 경계 표시(괄호) — 조건인지 결과인지 갈리지 않는 등위 접속"

    def _annotate_requests(self, question: str) -> tuple[str, str | None]:
        """요구가 여럿이고 그중 하나가 "if there is any" 처럼 **없을 수도 있는** 것이면, 요구를
        나눠 표시한다. 원문은 그대로 두고 뒤에 구조만 덧붙인다(2026-10-12 설계, BIRD 397·446).

        "List X and find Y if there are any" 는 Y 가 없어도 X 의 행을 살려야 한다는 뜻인데,
        모델은 Y 를 주는 테이블을 INNER JOIN 해 행을 버리거나(446), Y 를 행마다 펼친다(397).
        이 단계는 스키마를 모르므로 조인 종류를 정할 수 없다 — 값 수준의 허용("값이 없어도
        행을 빼지 말 것")만 명시하고 판단은 생성 단계에 맡긴다.

        LLM 을 타지 않는다. **표지가 있을 때만** 붙이므로 다른 질문의 프롬프트는 글자 하나
        바뀌지 않는다(전역 규칙 문구 변경이 무관한 문항을 흔들던 문제를 피함).
        """
        q = question.strip()
        if not _OPTIONAL_MARK.search(q):
            return question, None
        parts: list[str] = []
        for sentence in re.split(r"(?<=[?.])\s+", q):
            pieces = [p.strip() for p in _SECOND_REQUEST.split(sentence) if p and p.strip()]
            parts.extend(pieces)
        requests = [p for p in parts if _ASK_VERB.search(p) or _OPTIONAL_MARK.search(p)]
        if len(requests) < 2:
            return question, None
        lines = []
        for i, r in enumerate(requests, 1):
            if _OPTIONAL_MARK.search(r):
                lines.append(f"{i}. {r} (선택 — 이 값이 없어도 앞 요구의 행은 빼지 말 것)")
            else:
                lines.append(f"{i}. {r}")
        annotated = f"{q}\n[요구 구분]\n" + "\n".join(lines)
        return annotated, f"요구 구분 표시 — 요구 {len(requests)}개, 선택 표지 있음"

    def _detect_pattern_ambiguity(self, question: str) -> AmbiguitySignal:
        reasons = [p.pattern for p in _AMBIGUOUS_DATE_PATTERNS if p.search(question)]
        return AmbiguitySignal(found=bool(reasons), reasons=reasons)

    async def _detect_semantic_ambiguity(self, question: str) -> AmbiguitySignal:
        """패턴으로 못 잡는 의미적 모호성(질문이 서로 다른 SQL로 이어질 수 있는 여러
        해석을 허용하는지)을 LLM으로 2차 판단한다. 파싱을 단순하게 유지하기 위해
        정해진 두 줄 형식으로만 응답하게 한다."""
        prompt = (
            "다음 질문이 데이터베이스 질의로 바로 옮기기에 모호한지 판단하세요. "
            "모호함이란 동일 질문이 서로 다른 SQL로 이어질 수 있는 여러 해석이 가능한 "
            "경우를 말합니다 (예: 기준이 불명확한 비교급/최상급 표현, 명시되지 않은 집계 "
            "단위, 여러 컬럼/테이블에 해당할 수 있는 모호한 지칭 등). "
            "정확히 아래 두 줄 형식으로만 답하세요.\n"
            "AMBIGUOUS: yes 또는 no\n"
            "REASON: 한 문장 이유 (모호하지 않으면 빈 문자열)"
        )
        resp = await self._detect_llm.complete(system_prompt=prompt, messages=[{"role": "user", "content": question}])
        text = resp.text or ""
        self._last_debug.append({"call": "enrich_detect", "prompt": f"{prompt}\n\n[입력]\n{question}", "response": text})
        found = bool(re.search(r"AMBIGUOUS:\s*yes", text, re.IGNORECASE))
        reason_match = re.search(r"REASON:\s*(.+)", text, re.IGNORECASE)
        reason = reason_match.group(1).strip() if reason_match else ""
        reasons = [reason] if found and reason else (["의미적으로 모호함 (LLM 판단)"] if found else [])
        if resp.usage:
            self._last_usage.append({"call": "enrich_detect", **resp.usage})
        return AmbiguitySignal(found=found, reasons=reasons)

    async def _rewrite(
        self, question: str, ambiguity: AmbiguitySignal, *,
        evidence: str | None = None, domain_hint: str | None = None,
    ) -> str:
        prompt = (
            "다음 질문의 모호한 표현을, 데이터베이스 질의에 바로 쓸 수 있도록 구체적인 표현으로 "
            "재작성하세요. 원래 의도를 벗어나지 마세요. 해석이 여러 갈래로 나뉠 수 있다면 "
            "그중 가장 통상적인 해석 하나만 골라 반영하세요.\n"
        )
        if evidence:
            # evidence는 여기서 참고 자료로만 쓴다 — 출력(재작성된 질문)에 evidence 자체를
            # 옮기거나 합치면 안 된다(그건 orchestrator가 재작성 이후 별도로 붙인다). 다만
            # evidence가 없으면, 모호성이 evidence로 이미 정밀하게 풀려있는데도 재작성이
            # 그 뉘앙스를 뭉개고 더 단순한(부정확한) 표현으로 바꿔버리는 걸 실측으로 확인했다
            # (예: evidence가 "sum(평균)/count(학교수)"로 집계 방식을 명시했는데, 재작성이
            # 이를 무시하고 그냥 "평균 점수"로 뭉뚱그림 — downstream SQL이 GROUP BY/HAVING
            # 대신 단순 비교로 잘못 생성됨).
            prompt += (
                "다음 참고 정보(evidence)가 모호성을 이미 구체적으로 풀어주는 부분이 있다면 "
                "그 뉘앙스(특히 계산식·집계 방식·조건)를 재작성에 반영하세요 — 참고 정보가 "
                "이미 정밀하게 정의한 내용을 임의로 단순화하거나 생략하지 마세요. 단, 참고 "
                "정보 자체를 출력에 그대로 옮기거나 질문과 합치지는 마세요.\n"
                f"[참고 정보 — 이해에만 참고하고 출력에는 포함하지 말 것]\n{evidence}\n\n"
            )
        if domain_hint:
            # domain_hint(glossary)도 evidence와 같은 이유로 참고만 하고 출력엔 안 섞는다 —
            # "average score in writing이 이미 avgscrwrite 컬럼이다" 같은 지식이 있으면,
            # 이미 존재하는 값을 "새로 집계해야 할 것"처럼 재작성하지 않도록 막는 용도다.
            prompt += (
                "다음은 이 도메인에서 이미 정의된 용어/컬럼 지식입니다. 질문에 나온 표현이 "
                "여기 정의된 값을 가리키는 것이라면, 그걸 새로 계산해야 하는 것처럼 재작성하지 "
                "마세요. 단, 이 지식 자체를 출력에 그대로 옮기지는 마세요.\n"
                f"[도메인 지식 — 이해에만 참고하고 출력에는 포함하지 말 것]\n{domain_hint}\n\n"
            )
        prompt += (
            "출력은 재작성된 질문 한 문장뿐이어야 합니다. 설명, 여러 해석의 나열, 이유, "
            "예시 SQL, 코드 블록은 절대 포함하지 마세요.\n\n"
            f"질문: {question}\n모호성 신호: {ambiguity.reasons}"
        )
        resp = await self._rewrite_llm.complete(system_prompt=prompt, messages=[{"role": "user", "content": question}])
        self._last_debug.append({"call": "enrich_rewrite", "prompt": prompt, "response": resp.text or ""})
        if resp.usage:
            self._last_usage.append({"call": "enrich_rewrite", **resp.usage})
        rewritten = (resp.text or "").strip()
        if not rewritten or "\n" in rewritten or "```" in rewritten:
            # 형식 지시를 무시하고 여러 줄/코드블록을 반환하면, 존재하지 않는 테이블·컬럼을
            # 예시로 지어내 downstream(스키마 링킹/SQL 생성)을 오염시킬 위험이 있다 — 이 경우
            # 재작성을 포기하고 원문을 그대로 쓴다.
            return question
        return rewritten
