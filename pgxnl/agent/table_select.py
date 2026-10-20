"""테이블 선택 단계 — SQL 생성과 분리한 LLM 스키마 링킹(2026-10-15 실험).

지금 파이프라인은 임베딩으로 후보 테이블을 넉넉히 고른 뒤 ReAct 한 번이 "어떤 테이블·조인을 쓸지"와
"SQL 작성"을 함께 한다. 이 모듈은 앞의 판단만 따로 LLM 에 맡긴다 — 질문과 스키마 전체를 보고
필요한 테이블과 조인만 JSON 으로 고른다. 파이프라인에 연결하기 전에 정확도(gold 테이블을 빠짐없이
고르는가)와 시간을 먼저 재기 위한 것이다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pgxnl.llm.base import BaseLLMClient

SYSTEM_PROMPT = (
    "당신은 데이터베이스 스키마 분석가입니다. 아래 스키마를 보고, 질문에 답하는 SQL 을 쓰는 데 "
    "필요한 테이블과 조인만 고르세요. SQL 은 쓰지 마세요.\n"
    "출력은 JSON 한 개만: {\"tables\": [\"테이블\", ...], \"joins\": [\"a.x=b.y\", ...], \"reason\": \"한두 문장\"}\n"
    "조인이 필요 없으면 joins 는 빈 배열입니다. reason 에는 왜 이 테이블과 조인을 골랐는지 적으세요."
)

_JSON = re.compile(r"\{.*\}", re.S)


@dataclass
class TableSelection:
    tables: list[str]
    joins: list[str] = field(default_factory=list)
    reason: str = ""
    raw: str = ""
    error: str | None = None


def build_schema_text(blocks: list[str]) -> str:
    """테이블별 M-Schema 블록(용어집 포함)을 이어 붙인다."""
    return "\n\n".join(blocks)


def parse_selection(text: str | None, known_tables: set[str]) -> TableSelection:
    """모델 출력에서 JSON 을 꺼낸다. 스키마에 없는 테이블 이름은 버린다(대소문자 무시)."""
    raw = text or ""
    m = _JSON.search(raw)
    if not m:
        return TableSelection(tables=[], raw=raw, error="JSON 없음")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return TableSelection(tables=[], raw=raw, error=f"JSON 오류: {exc}")
    lower = {t.lower(): t for t in known_tables}
    tables: list[str] = []
    for t in data.get("tables") or []:
        name = str(t).split(".")[-1].strip('"').lower()
        if name in lower and lower[name] not in tables:
            tables.append(lower[name])
    joins = [str(j) for j in data.get("joins") or []]
    return TableSelection(tables=tables, joins=joins, reason=str(data.get("reason") or ""), raw=raw)


async def select_tables(
    llm: BaseLLMClient, question: str, schema_text: str, known_tables: set[str],
) -> TableSelection:
    resp = await llm.complete(
        system_prompt=f"{SYSTEM_PROMPT}\n\n[스키마]\n{schema_text}",
        messages=[{"role": "user", "content": question}],
    )
    return parse_selection(resp.text, known_tables)
