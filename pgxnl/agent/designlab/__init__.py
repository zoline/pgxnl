"""Design Lab — 대상 DB 스키마의 정규형을 검토한다.

이 계층은 **전부 결정론적**이다(LLM 호출 없음, ADR-0009). 카탈로그와 데이터만 읽어
"이 스키마에서 자연어 질의가 구조적으로 모호해지는 지점"을 찾아낸다.

동기(실측 2026-09-03~04, BIRD `california_schools`): 같은 개념(학교 이름)이 3개
테이블에 중복돼 있고 값까지 2.5~4.5% 갈린다. **30문항 중 12개(40%)가 그런 컬럼을
gold에서 쓴다** — 모델이 정답 논리를 알아도 다른 테이블의 사본을 고르면 틀린다.
프롬프트를 어떻게 배치해도(용어집 위치를 바꿔봤다) 우연에 좌우될 뿐이었다.

**마이그레이션 도구가 아니다.** 사용자의 운영 스키마를 우리가 바꿀 수 없으므로,
출력은 "진단 + 지금 할 수 있는 대응"이어야 한다.
"""
from pgxnl.agent.designlab.analyzer import (
    DuplicateConcept,
    Finding,
    RepeatingGroup,
    SchemaReport,
    TransitiveDependency,
    analyze_schema,
)

__all__ = [
    "DuplicateConcept",
    "Finding",
    "RepeatingGroup",
    "SchemaReport",
    "TransitiveDependency",
    "analyze_schema",
]
