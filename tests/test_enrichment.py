"""질문 보강(QuestionEnricher) 단위 테스트. design 문서 §5.2 참고.

모호성 판단(enrich_detect)과 재작성(enrich_rewrite)은 서로 다른 LLM 프로필을 지정할
수 있도록 별도 클라이언트로 주입받는다 — 테스트에서도 두 페이크 클라이언트를 분리해,
어느 단계가 실제로 호출됐는지 각자 검증한다.
"""
from dataclasses import dataclass, field

from pgxnl.agent.enrichment import QuestionEnricher
from pgxnl.llm.base import BaseLLMClient, LLMResponse


@dataclass
class FakeLLMClient(BaseLLMClient):
    responses: list[str | None] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    message_contents: list[str] = field(default_factory=list)
    provider: str = "fake"

    async def complete(self, system_prompt, messages, tools=None):
        self.calls.append(system_prompt)
        self.message_contents.append(messages[0]["content"])
        text = self.responses.pop(0) if self.responses else None
        return LLMResponse(text=text, tool_calls=[], stop_reason="end_turn")

    def format_assistant_message(self, response):
        raise NotImplementedError

    def format_tool_results(self, results):
        raise NotImplementedError


async def test_disabled_returns_original_without_llm_call():
    detect_llm, rewrite_llm = FakeLLMClient(), FakeLLMClient()
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=False)

    result = await enricher.enrich("최근 주문 몇 건이야?")

    assert result.text == "최근 주문 몇 건이야?"
    assert result.rewritten is False
    assert detect_llm.calls == []
    assert rewrite_llm.calls == []


async def test_pattern_ambiguity_triggers_rewrite_without_extra_semantic_call():
    detect_llm = FakeLLMClient()
    rewrite_llm = FakeLLMClient(responses=["지난 7일간 주문 몇 건이야?"])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    result = await enricher.enrich("최근 주문 몇 건이야?")

    assert result.rewritten is True
    assert result.text == "지난 7일간 주문 몇 건이야?"
    assert result.original == "최근 주문 몇 건이야?"
    # 1차 패턴에서 이미 모호성을 찾았으므로 2차(의미 기반) 판단 호출은 건너뛰고
    # 재작성 호출 한 번만 발생해야 한다 (중복 호출 방지).
    assert detect_llm.calls == []
    assert len(rewrite_llm.calls) == 1


async def test_no_ambiguity_without_semantic_check_skips_llm_entirely():
    detect_llm, rewrite_llm = FakeLLMClient(), FakeLLMClient()
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=False)

    result = await enricher.enrich("올해 매출 총액은?")

    assert result.rewritten is False
    assert result.text == "올해 매출 총액은?"
    assert detect_llm.calls == []
    assert rewrite_llm.calls == []


async def test_semantic_ambiguity_detected_triggers_rewrite():
    detect_llm = FakeLLMClient(responses=["AMBIGUOUS: yes\nREASON: '큰' 고객의 기준이 불명확함"])
    rewrite_llm = FakeLLMClient(responses=["매출 상위 10개 고객은?"])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    result = await enricher.enrich("큰 고객이 누구야?")

    assert result.rewritten is True
    assert result.text == "매출 상위 10개 고객은?"
    assert result.reasons == ["'큰' 고객의 기준이 불명확함"]
    assert len(detect_llm.calls) == 1
    assert len(rewrite_llm.calls) == 1


async def test_semantic_check_not_ambiguous_returns_original():
    detect_llm = FakeLLMClient(responses=["AMBIGUOUS: no\nREASON: "])
    rewrite_llm = FakeLLMClient()
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    result = await enricher.enrich("고객 수는 몇 명이야?")

    assert result.rewritten is False
    assert result.text == "고객 수는 몇 명이야?"
    assert len(detect_llm.calls) == 1
    assert rewrite_llm.calls == []


async def test_rewrite_falls_back_to_original_when_llm_returns_empty():
    detect_llm = FakeLLMClient()
    rewrite_llm = FakeLLMClient(responses=[None])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=False)

    result = await enricher.enrich("최근 재고 현황은?")

    assert result.rewritten is True  # 재작성을 시도했다는 사실 자체는 유지
    assert result.text == "최근 재고 현황은?"  # 결과가 비어 원문으로 폴백


async def test_rewrite_falls_back_when_llm_ignores_single_line_format():
    # 실서비스에서 관측된 회귀 케이스: 재작성 대신 여러 해석 + 예시 SQL을 늘어놓으면
    # 존재하지 않는 테이블/컬럼이 downstream(스키마 링킹)으로 흘러 들어갈 수 있다.
    verbose_response = (
        "기준에 따라 여러 해석이 가능합니다.\n"
        "1. 수입 기준: SELECT name FROM actors ORDER BY income DESC\n"
        "2. 인기 기준: ```sql\nSELECT name FROM actors ORDER BY followers DESC\n```"
    )
    detect_llm = FakeLLMClient()
    rewrite_llm = FakeLLMClient(responses=[verbose_response])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=False)

    result = await enricher.enrich("최근 제일 잘 나가는 배우는?")

    assert result.rewritten is True
    assert result.text == "최근 제일 잘 나가는 배우는?"  # 여러 줄/코드블록 응답은 원문으로 폴백


async def test_rewrite_accepts_clean_single_line_response():
    detect_llm = FakeLLMClient()
    rewrite_llm = FakeLLMClient(responses=["매출 기준 상위 1명의 배우는 누구인가요?"])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=False)

    result = await enricher.enrich("최근 제일 잘 나가는 배우는?")

    assert result.text == "매출 기준 상위 1명의 배우는 누구인가요?"


async def test_evidence_is_shown_to_ambiguity_detection():
    # evidence가 있으면 모호성 판단(패턴/의미 둘 다)이 question+evidence를 함께 본다 —
    # evidence가 이미 모호함을 풀어주는 경우까지 재작성 대상으로 잡히는 걸 막기 위함
    # (실서비스에서 관측: evidence 없이 판단하면 불필요한 재작성이 발동해 SQL 컬럼
    # 구성/순서가 흔들렸다). 이어붙이는 형식도 실측으로 검증됨 — "[참고 정보]" 헤더로
    # 구조적으로 분리하면 모델이 순수 질문 부분만 다시 놓고 evidence와 무관한 별개의
    # 모호함까지 찾아내 재작성이 더 자주 발동했다(3번 중 2번). 한 문장처럼 자연스럽게
    # 이어붙이면 훨씬 안정적으로 재작성이 불필요하다고 판단했다(3번 중 3번) — 그래서
    # 공백으로만 이어붙인다.
    detect_llm = FakeLLMClient(responses=["AMBIGUOUS: no\nREASON: "])
    rewrite_llm = FakeLLMClient()
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    result = await enricher.enrich("차터 번호를 보여줘", evidence="유효한 차터 번호는 NULL이 아닌 값이다")

    assert detect_llm.message_contents[0] == "차터 번호를 보여줘 유효한 차터 번호는 NULL이 아닌 값이다"
    assert result.rewritten is False
    assert result.text == "차터 번호를 보여줘"  # evidence는 여기서 다시 안 붙는다 — orchestrator가 붙임


async def test_rewrite_receives_bare_question_without_evidence():
    # 재작성 대상은 evidence를 뺀 순수 질문이어야 한다 — evidence 재부착은
    # orchestrator.analyze()가 재작성 이후 별도로 하므로, 여기서 섞으면 중복된다.
    detect_llm = FakeLLMClient(responses=["AMBIGUOUS: yes\nREASON: 모호함"])
    rewrite_llm = FakeLLMClient(responses=["재작성된 질문"])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    await enricher.enrich("애매한 질문", evidence="참고 사항")

    assert detect_llm.message_contents[0] == "애매한 질문 참고 사항"  # 판단 단계는 evidence를 봄
    assert rewrite_llm.message_contents[0] == "애매한 질문"  # 재작성 단계는 순수 질문만 봄


async def test_rewrite_sees_evidence_as_reference_but_not_in_message():
    # evidence가 이미 정밀하게 정의한 계산식/조건(예: "sum(평균)/count(학교수)")을 재작성이
    # 무시하고 더 단순한 표현으로 뭉개버리는 사례를 실측으로 확인했다 — 재작성 LLM의
    # system_prompt에는 evidence를 참고 자료로 전달해 이 뉘앙스를 지키게 유도하되,
    # messages(질문 본문)에는 여전히 evidence를 안 섞는다(위 테스트와 대비되는 지점).
    detect_llm = FakeLLMClient(responses=["AMBIGUOUS: yes\nREASON: 집계 방식 모호함"])
    rewrite_llm = FakeLLMClient(responses=["재작성된 질문"])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    await enricher.enrich("평균의 평균이 400 초과인 학교는?", evidence="sum(평균) / count(학교수)")

    assert "sum(평균) / count(학교수)" in rewrite_llm.calls[0]  # system_prompt에는 evidence 포함
    assert rewrite_llm.message_contents[0] == "평균의 평균이 400 초과인 학교는?"  # messages엔 여전히 안 섞임


async def test_domain_hint_suppresses_false_ambiguity_and_stays_out_of_output():
    # 실측 사례: "average score in writing"이 이미 존재하는 컬럼(avgscrwrite)인데도
    # 모호성 감지기가 "집계값과 개별 나열이 섞여 모호하다"고 오판해, 재작성이 "전체
    # 평균도 계산해달라"는 요구를 새로 만들어내 SQL에 불필요한 집계가 추가되는 걸
    # 확인했다 — enrichment는 스키마를 모르므로, orchestrator가 glossary에서 미리
    # 찾아준 도메인 지식(domain_hint)을 판단 단계에 보여주면 이런 오판을 줄일 수 있다.
    # domain_hint도 evidence와 마찬가지로 "판단에는 보여주되 출력엔 안 섞는다".
    detect_llm = FakeLLMClient(responses=["AMBIGUOUS: no\nREASON: "])
    rewrite_llm = FakeLLMClient()
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    result = await enricher.enrich(
        "학교별 평균 작문 점수는?", domain_hint="average score in writing: avgscrwrite 컬럼을 가리킴"
    )

    assert "avgscrwrite 컬럼을 가리킴" in detect_llm.message_contents[0]  # 판단 단계는 domain_hint를 봄
    assert result.rewritten is False
    assert result.text == "학교별 평균 작문 점수는?"  # domain_hint 자체는 출력에 안 섞임


async def test_detect_and_rewrite_use_independent_clients():
    # 두 단계가 서로 다른 LLM 프로필을 써도(예: 판단은 저렴한 모델, 재작성은 더 좋은
    # 모델) 각자 자기 몫만 호출해야 한다 — 클라이언트가 섞이면 안 된다.
    detect_llm = FakeLLMClient(responses=["AMBIGUOUS: yes\nREASON: 기준 불명확"])
    rewrite_llm = FakeLLMClient(responses=["재작성된 질문"])
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=True)

    await enricher.enrich("애매한 질문")

    assert detect_llm.responses == []  # detect_llm이 소비함
    assert rewrite_llm.responses == []  # rewrite_llm이 소비함



# ------------------------------------------------- 조건절 경계 표시 (결정론적 괄호 삽입)

def _bracket(question: str) -> tuple[str, str | None]:
    enricher = QuestionEnricher(FakeLLMClient(), FakeLLMClient(), enabled=True)
    return enricher._bracket_conditions(question)


def test_brackets_condition_with_coordination():
    # BIRD 443: `and` 뒤가 두 번째 요구인지 두 번째 조건인지 문장 구조로는 안 갈린다.
    # 모델은 일관되게 "요구"로 읽어 SELECT에 넣었고 gold는 조건으로 읽었다. 괄호로
    # 경계를 표시하자 SELECT에서 빠지고 조건절도 gold와 같아졌다(실측).
    q = ("Give the names of the schools with the percent eligible for free meals in K-12 "
         "is more than 0.1 and test takers whose test score is greater than or equal to 1500?")
    out, reason = _bracket(q)

    assert out == (
        "Give the names of the schools with (the percent eligible for free meals in K-12 "
        "is more than 0.1 and test takers whose test score is greater than or equal to 1500)?"
    )
    assert reason is not None
    # 원문 글자는 하나도 안 바뀐다 — 괄호만 추가된다.
    assert out.replace("(", "").replace(")", "") == q


def test_no_coordination_means_nothing_to_bracket():
    q = "Give the names of the schools with more than 500 students?"
    assert _bracket(q) == (q, None)


def test_existing_parentheses_are_left_alone():
    # 사람이 의도해 묶은 것을 덮어쓰면 안 된다.
    q = "List the schools with (a rate over 0.1 and a score over 1500)?"
    assert _bracket(q) == (q, None)


def test_along_with_is_not_a_condition_head():
    # 실측 seq 204: "Name the races along with its circuit name and location" — gold 3컬럼.
    # `along with` 뒤는 조건이 아니라 추가 요구라, 묶으면 요구 컬럼을 조건으로 만든다.
    q = "Name the races along with its circuit name and location for f1 races hosted in September 2005."
    assert _bracket(q) == (q, None)


def test_request_verb_inside_region_blocks_bracketing():
    # 실측 seq 71 / 133: `include`, `how many`가 들어 있으면 그건 두 번째 요구다(gold 다컬럼).
    for q in (
        ("List the last name of members with a major in environmental engineering "
         "and include its department and college name."),
        ("Give the name of the league with the highest matches of all time and "
         "how many matches were played in the said league."),
    ):
        assert _bracket(q) == (q, None)


def test_multiple_request_sentences_are_skipped():
    # 어느 문장의 조건인지 정할 수 없다.
    q = "What is the amount spent by customer 38508 with tax and fees? How much did others pay?"
    assert _bracket(q) == (q, None)


def test_condition_marker_before_ask_verb_is_ignored():
    # "For patients with X, list Y" — 앞쪽 with를 경계로 잡으면 엉뚱한 데를 묶는다.
    q = "For patients with severe thrombosis, list their ID and sex."
    out, reason = _bracket(q)
    assert reason is None and out == q


async def test_bracketing_happens_without_any_llm_call():
    # 결정론적 단계다 — 모호성 판단이 필요 없는 질문이면 LLM을 한 번도 안 부른다.
    detect_llm, rewrite_llm = FakeLLMClient(), FakeLLMClient()
    enricher = QuestionEnricher(detect_llm, rewrite_llm, enabled=True, semantic_check_enabled=False)

    result = await enricher.enrich("List the schools with a rate over 0.1 and a score over 1500?")

    assert result.text == "List the schools with (a rate over 0.1 and a score over 1500)?"
    assert result.rewritten is True
    assert detect_llm.calls == [] and rewrite_llm.calls == []
