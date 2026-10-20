"""generate_sql 도구. design 문서 §5.7 참고.

축소된 스키마 컨텍스트(M-Schema) + few-shot 프롬프트로 SQL을 생성한다. 실행 자체는
이 도구가 하지 않는다 — 문법 오류가 있으면 오류 메시지를 근거로 최대
PGXNL_AGENT_MAX_CORRECTIONS회까지 스스로 재생성을 시도한 뒤, 최종 SQL은
Canonicalization(§5.8) -> 검증(§5.9)을 거쳐서만 실행된다.
"""
from __future__ import annotations

import re

from pgxnl.llm.base import BaseLLMClient
from pgxnl.parsing.base import SqlParser

_FENCE_PATTERN = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


class SqlGenerationError(Exception):
    pass


def strip_code_fence(text: str) -> str:
    """LLM 응답에서 ```sql ... ``` 코드펜스를 벗긴다.

    예전 구현은 `.strip("```sql").strip("```")`였는데, `str.strip`의 인자는
    부분문자열이 아니라 **문자 집합**이다 — 코드펜스 없이 SQL만 돌아오면 끝의
    `s`/`q`/`l`/백틱이 그대로 잘렸다. `SELECT * FROM schools`가
    `SELECT * FROM schoo`가 되어 "존재하지 않는 테이블" 오류로 이어진다(실측).
    """
    text = text.strip()
    match = _FENCE_PATTERN.match(text)
    return match.group(1).strip() if match else text


async def generate_sql(
    llm: BaseLLMClient,
    parser: SqlParser,
    question: str,
    schema_context: str,
    *,
    max_corrections: int = 3,
) -> str:
    system_prompt = (
        "당신은 PostgreSQL 전문가입니다. 아래 스키마만 사용해 질문에 답하는 "
        "단일 SELECT 문을 작성하세요. 다른 설명 없이 SQL만 반환하세요."
    )
    if "[SQL 생성 규칙]" in schema_context or "[Few-shot 예시]" in schema_context:
        system_prompt += (
            " 아래 [스키마] 안에 [SQL 생성 규칙] 섹션이 있다면 SQL 문법 규칙처럼 반드시 "
            "지키고, [Few-shot 예시] 섹션이 있다면 그 판단 기준을 동일하게 적용하세요."
        )
    system_prompt += f"\n\n[스키마]\n{schema_context}"
    messages = [{"role": "user", "content": question}]

    last_error: str | None = None
    for attempt in range(max_corrections + 1):
        prompt = system_prompt
        if last_error:
            prompt += f"\n\n[이전 시도 오류]\n{last_error}\n오류를 피해 다시 작성하세요."
        resp = await llm.complete(system_prompt=prompt, messages=messages)
        sql = strip_code_fence(resp.text or "")
        try:
            stmt = parser.parse(sql)  # 문법 검증만 수행, 실행은 하지 않는다
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
        # parse()는 문법 오류에 예외를 던지지 않는다 — ANTLR이 복구해서 불완전한 트리를
        # 돌려주기 때문이다. 그래서 예외만 잡던 예전 코드에서는 이 재시도 루프가 한 번도
        # 발동하지 않았고, 깨진 SQL이 그대로 통과했다(실측 2026-09-03). 오류 목록을
        # 직접 확인하고, 그 내용을 재작성 힌트로 모델에게 돌려준다.
        if stmt.is_well_formed:
            return sql
        last_error = "SQL 구문 오류: " + "; ".join(stmt.syntax_errors[:3])

    raise SqlGenerationError(f"{max_corrections}회 재시도 후에도 유효한 SQL을 생성하지 못했습니다: {last_error}")
