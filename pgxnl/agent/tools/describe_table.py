"""describe_table 도구. design 문서 §5.7 참고.

캐시 히트 시 DB 쿼리를 생략한다. glossary_store가 있으면 컬럼 설명에 업무 용어 정의를
함께 붙여 반환한다.

스키마 벡터는 여기서 더 이상 자동 갱신하지 않는다 — describe_table이 호출될 때마다
해당 테이블만 개별 재임베딩되던 방식이, 사용 패턴에 따라 일부 테이블은 최근 값
나머지는 과거 값으로 세대가 섞이는 문제를 실측으로 일으켰다(§5.4 참고). 필요할 때
명시적으로 재색인하도록 관리 API로 옮겼다(`POST /api/admin/targets/{name}/schema-vector/table`
또는 전체 재구축 `DELETE .../schema-vector`).
"""
from __future__ import annotations

from typing import Any

from pgxnl.cache.schema import SchemaCache
from pgxnl.connectors.postgresql import PgConnector
from pgxnl.governance.glossary import GlossaryStore


def _rows(items: list[Any], columns: list[str]) -> dict:
    """LLM에 보낼 목록형 데이터를 {columns, rows} 형태로 압축한다 — 항목마다 키 이름을
    반복하는 JSON 객체 배열([{"a":1,"b":2},{"a":3,"b":4}])보다, 헤더 한 번 + 값 배열의
    배열([[1,2],[3,4]])이 컬럼/glossary 항목이 늘어날수록 토큰을 적게 쓴다. ReAct 루프가
    매 반복 전체 대화를 재전송하는 구조라(§5.5) 이 반복이 누적되면 낭비가 커진다는 걸
    실측으로 확인했다(사용자 지적)."""
    return {"columns": columns, "rows": [[getattr(it, c) for c in columns] for it in items]}


async def describe_table(
    conn: PgConnector,
    cache: SchemaCache,
    glossary: GlossaryStore | None,
    target_name: str,
    schema: str,
    table: str,
) -> dict:
    cache_key = f"ddl:{schema}.{table}"
    cached = await cache.get(target_name, cache_key)
    if cached is None:
        cached = await _describe_uncached(conn, schema, table)
        await cache.set(target_name, cache_key, cached)

    # 용어집은 캐시하지 않고 **매번** 붙인다(2026-10-07). 전엔 DDL과 함께 캐시돼(TTL 24시간) 용어집을
    # 고쳐도 이 도구 출력엔 최대 하루 전 용어집이 나왔다 — 스키마 컨텍스트([용어집])와 내용이 달랐고,
    # 캐시가 평가 도중 만료되면서 측정 조건이 몰래 바뀌었다(run 375·376). 조회는 가벼운 쿼리 하나다.
    result = {k: v for k, v in cached.items() if k != "glossary"}
    if glossary is not None:
        entries = await glossary.for_table(target_name, schema, table)
        # LLM에는 SQL 생성에 실제로 쓰이는 필드만 넘긴다 — id/schema_name/table_name(이미
        # 이 테이블로 스코핑됨, 중복)/source(관리자용 출처 URL)/scope(admin 라우팅 전용)는
        # ReAct 루프가 매 반복 전체 대화를 재전송하는 구조라 반복될수록 토큰 낭비가
        # 누적된다는 지적을 실측으로 확인해 뺐다.
        result["glossary"] = _rows(entries, ["term", "column_name", "definition", "is_pii"])
    return result


async def _describe_uncached(conn: PgConnector, schema: str, table: str) -> dict:
    meta = await conn.describe_table(schema, table)
    # example_values는 describe_table()이 채우는 값이 아니라 항상 None이라(실측 확인,
    # postgresql.py의 컬럼 조회 쿼리에 없음) 매번 "example_values": null만 반복해서
    # 보내는 순수 낭비였다 — 이 도구 출력에서는 뺀다(M-Schema 쪽 example_values 활용은
    # 별개 경로라 dataclass 자체는 안 건드림).
    result: dict = {
        "schema": meta.schema, "name": meta.name, "comment": meta.comment,
        "columns": _rows(meta.columns, ["name", "data_type", "comment", "is_primary_key"]),
        "foreign_keys": meta.foreign_keys,
    }
    return result
