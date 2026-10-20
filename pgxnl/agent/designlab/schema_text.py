"""LLM 단독 검토용 스키마 정의 텍스트.

Design Lab의 "LLM 의견 — 스키마 정의만으로" 옵션은 결정론적 findings 없이
테이블 정의만 LLM에게 준다. 큰 스키마는 정의만으로도 컨텍스트를 넘길 수 있어
(sample_data 49컬럼×50행 사고와 같은 종류) 글자 수 상한을 둔다 — 넘치면
뒤쪽 테이블을 빼고, 몇 개를 뺐는지 호출부가 LLM과 사용자 양쪽에 알린다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 스키마 정의 텍스트 상한(글자). 약 10k 토큰 — 응답 여유를 남긴다.
SCHEMA_TEXT_LIMIT = 40_000


@dataclass(frozen=True)
class SchemaText:
    text: str
    included: int
    omitted: list[str]


def render_table(t: Any) -> str:
    """TableMeta 하나를 간결한 CREATE TABLE 비슷한 텍스트로."""
    lines = [f"TABLE {t.name}" + (f"  -- {t.comment}" if t.comment else "")]
    fk_by_col = {local: f"{ref_t}.{ref_c}" for local, ref_t, ref_c in t.foreign_keys}
    for c in t.columns:
        tags = []
        if c.is_primary_key:
            tags.append("PK")
        if c.name in fk_by_col:
            tags.append(f"FK→{fk_by_col[c.name]}")
        line = f"  {c.name} {c.data_type}"
        if tags:
            line += " [" + ", ".join(tags) + "]"
        if c.comment:
            line += f"  -- {c.comment}"
        lines.append(line)
    return "\n".join(lines)


def render_schema(tables: list[Any], limit: int = SCHEMA_TEXT_LIMIT) -> SchemaText:
    """테이블 순서대로 붙이다가 상한을 넘기는 테이블부터는 뺀다."""
    blocks: list[str] = []
    size = 0
    omitted: list[str] = []
    for t in tables:
        block = render_table(t)
        if omitted or size + len(block) + 2 > limit:
            omitted.append(t.name)
            continue
        blocks.append(block)
        size += len(block) + 2
    return SchemaText(text="\n\n".join(blocks), included=len(blocks), omitted=omitted)
