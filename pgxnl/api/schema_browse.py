"""Schema 탐색 / 실행계획 API가 공유하는 로직.

admin 전용 라우트(routes_admin.py, 시스템 계정으로 조회)와 일반 사용자 라우트
(routes_analyze.py, 사용자별 DB 자격증명 존중)가 동일한 조회 로직을 쓴다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ExplainBody(BaseModel):
    sql: str
    analyze: bool = False
    schema_name: str = "public"


async def browse_schema_data(orchestrator: Any, search: str = "") -> dict:
    """대상 DB의 모든 스키마를 순회해 테이블/컬럼/PK/FK/인덱스를 한 번에 반환한다.

    실시간 카탈로그 조회이며 서버 쪽 캐시를 두지 않는다.
    """
    search_lower = search.lower().strip()
    results = []
    schemas = await orchestrator.list_schemas()
    for schema in schemas:
        try:
            indexes = await orchestrator.list_indexes(schema)
        except Exception:  # noqa: BLE001
            indexes = []
        idx_by_table: dict[str, list] = {}
        for idx in indexes:
            idx_by_table.setdefault(idx.table, []).append(
                {"name": idx.name, "is_primary": idx.is_primary, "is_unique": idx.is_unique, "definition": idx.definition}
            )

        tables = await orchestrator.list_tables(schema)
        for t in tables:
            try:
                meta = await orchestrator.describe_table(schema, t.name)
            except Exception:  # noqa: BLE001
                continue
            fk_map = {fk[0]: {"table": fk[1], "column": fk[2]} for fk in meta.foreign_keys}
            columns = [
                {
                    "name": c.name, "type": c.data_type, "comment": c.comment,
                    "is_pk": c.is_primary_key, "fk": fk_map.get(c.name),
                }
                for c in meta.columns
            ]
            if search_lower:
                haystack = " ".join(
                    [schema, t.name, meta.comment or "", *(c["name"] for c in columns), *(c["comment"] or "" for c in columns)]
                ).lower()
                if search_lower not in haystack:
                    continue
            results.append({
                "schema": schema, "table": t.name, "comment": meta.comment,
                "columns": columns, "indexes": idx_by_table.get(t.name, []),
            })
    return {"tables": results}
