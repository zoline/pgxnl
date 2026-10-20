"""업무 용어집 레지스트리. design 문서 §5.11 참고.

describe_table 도구(§5.7)에 동적으로 주입되어 컬럼 의미를 보강하고, 검증
계층(§5.9)의 민감 필드(PII) 탐지에도 사용된다.
"""
from __future__ import annotations

from dataclasses import dataclass

import asyncpg

GENERATION_SCOPES = ("generation", "both")
ENRICH_SCOPES = ("enrich", "both")
SCOPES = ("enrich", "generation", "both", "disabled")


@dataclass
class GlossaryEntry:
    id: int
    term: str
    table_name: str | None
    column_name: str | None
    definition: str
    is_pii: bool
    schema_name: str | None = None
    source: str | None = None
    scope: str = "both"
    # 관리 화면(list_all)에서만 채운다 — 등록 시점 카탈로그 대조에 어느 대상 DB를
    # 볼지 알아야 한다. for_table()/for_enrichment()는 이미 target을 알고 조회하므로
    # 굳이 실어 나르지 않는다.
    target_name: str | None = None


class GlossaryStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def for_table(self, target_name: str, schema_name: str, table_name: str) -> list[GlossaryEntry]:
        """SQL 생성(schema_context) 경로 전용 — scope가 'generation'/'both'인 항목만
        돌려준다. schema_name: BIRD처럼 target_name 하나에 스키마가 여러 개면, 스키마
        구분 없이 table_name만으로 매칭할 경우 다른 스키마의 동명 테이블에도 잘못
        적용될 수 있다(시맨틱 캐시에서 겪은 것과 같은 문제) — schema_name이 NULL인
        항목은 target_name이 NULL인 것과 같은 관례로 "스키마 무관하게 적용"으로
        취급해 하위 호환한다. PII 탐지는 이 메서드를 쓰지 않는다 — pii_columns() 참고."""
        rows = await self._pool.fetch(
            f"""
            SELECT id, term, table_name, column_name, definition, is_pii, schema_name, source, scope
            FROM pgxnl_glossary
            WHERE (target_name = $1 OR target_name IS NULL)
              AND (schema_name = $2 OR schema_name IS NULL)
              AND table_name = $3
              AND scope IN ({",".join(f"'{s}'" for s in GENERATION_SCOPES)})
            ORDER BY id
            """,
            target_name, schema_name, table_name,
        )
        return [GlossaryEntry(**dict(r)) for r in rows]

    async def for_enrichment(self, target_name: str, schema_name: str) -> list[GlossaryEntry]:
        """질문 보강(enrichment) 경로 전용 — 스키마 링킹 이전이라 어느 테이블이 관련
        있는지 아직 모르므로 테이블 필터 없이 스키마 전체에서 scope가 'enrich'/'both'인
        항목만 가져온다. 관리자가 이 scope로 등록해둔 것만 대상이라 자동으로 토큰
        부담이 제한된다(DOC/SOC 같은 큰 값 표는 보통 'generation'으로만 등록될 것이므로
        여기 안 실림) — 질문과의 실제 관련성 필터링은 호출자(orchestrator)가 한다."""
        rows = await self._pool.fetch(
            f"""
            SELECT id, term, table_name, column_name, definition, is_pii, schema_name, source, scope
            FROM pgxnl_glossary
            WHERE (target_name = $1 OR target_name IS NULL)
              AND (schema_name = $2 OR schema_name IS NULL)
              AND scope IN ({",".join(f"'{s}'" for s in ENRICH_SCOPES)})
            ORDER BY id
            """,
            target_name, schema_name,
        )
        return [GlossaryEntry(**dict(r)) for r in rows]

    async def list_all(
        self, target_name: str | None = None, schema_name: str | None = None, scope: str | None = None,
    ) -> list[GlossaryEntry]:
        """관리 화면 조회용 — 등록이 늘어나면 스키마별로 걸러 보고 싶다는 요청으로
        schema_name 필터를, scope별로도 걸러 보고 싶다는 요청으로 scope 필터를
        추가했다. `for_table()`과 달리 여기서는 정확 매칭만 한다(관리자가 "이
        스키마/scope에만 적용되는 항목"을 보고 싶은 것이지, "실제로 유효한 전역
        항목까지 포함"을 보고 싶은 게 아니라서 스코프가 다르다). scope를 안 주면
        `for_table()`/`for_enrichment()`와 달리 전체(비활성 포함) 다 보여준다 —
        관리자가 다시 바꿀 수 있어야 하므로."""
        conditions = []
        params: list[str] = []
        if target_name is not None:
            params.append(target_name)
            conditions.append(f"(target_name = ${len(params)} OR target_name IS NULL)")
        if schema_name is not None:
            params.append(schema_name)
            conditions.append(f"schema_name = ${len(params)}")
        if scope is not None:
            params.append(scope)
            conditions.append(f"scope = ${len(params)}")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self._pool.fetch(
            f"SELECT id, term, table_name, column_name, definition, is_pii, schema_name, source, scope, "
            f"target_name FROM pgxnl_glossary {where} ORDER BY id",
            *params,
        )
        return [GlossaryEntry(**dict(r)) for r in rows]

    async def pii_columns(self, target_name: str, schema_name: str, table_name: str) -> set[str]:
        """PII 탐지는 검증 계층(§5.9)의 보안 기능이라 enrich/generation scope 구분과는
        무관하다 — 'disabled'만 아니면(즉 관리자가 명시적으로 끄지 않았으면) 어느
        scope든 is_pii 플래그를 반영해야 한다. for_table()을 그대로 쓰면 'enrich전용'으로
        등록된 PII 컬럼이 생성 경로에서 안 보인다는 이유로 PII 탐지에서도 조용히
        빠지는 보안 구멍이 생긴다 — 그래서 별도 쿼리를 쓴다."""
        rows = await self._pool.fetch(
            """
            SELECT column_name FROM pgxnl_glossary
            WHERE (target_name = $1 OR target_name IS NULL)
              AND (schema_name = $2 OR schema_name IS NULL)
              AND table_name = $3
              AND scope != 'disabled'
              AND is_pii
              AND column_name IS NOT NULL
            """,
            target_name, schema_name, table_name,
        )
        return {r["column_name"] for r in rows}

    async def create(
        self, target_name: str | None, term: str, definition: str, *,
        schema_name: str | None = None, table_name: str | None = None,
        column_name: str | None = None, is_pii: bool = False, source: str | None = None,
        scope: str = "both",
    ) -> int:
        row = await self._pool.fetchrow(
            """
            INSERT INTO pgxnl_glossary
                (target_name, schema_name, term, table_name, column_name, definition, is_pii, source, scope)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id
            """,
            target_name, schema_name, term, table_name, column_name, definition, is_pii, source, scope,
        )
        return row["id"]

    async def set_scope(self, entry_id: int, scope: str) -> None:
        await self._pool.execute(
            "UPDATE pgxnl_glossary SET scope=$1, updated_at=now() WHERE id=$2", scope, entry_id
        )

    async def update(
        self, entry_id: int, term: str, definition: str, *,
        target_name: str | None = None, schema_name: str | None = None, table_name: str | None = None,
        column_name: str | None = None, is_pii: bool = False, source: str | None = None,
    ) -> None:
        """create()와 달리 scope는 여기서 안 건드린다 — 수정 화면이 없어서 정의(예:
        따옴표 없는 코드값이 텍스트 컬럼과 타입 비교 오류를 내는 문제, BIRD 문항
        457번)를 고치려면 삭제 후 재등록해야 했던 걸 실측으로 확인해 추가했다."""
        await self._pool.execute(
            """
            UPDATE pgxnl_glossary
            SET term=$1, definition=$2, target_name=$3, schema_name=$4, table_name=$5,
                column_name=$6, is_pii=$7, source=$8, updated_at=now()
            WHERE id=$9
            """,
            term, definition, target_name, schema_name, table_name, column_name, is_pii, source, entry_id,
        )

    async def delete(self, entry_id: int) -> None:
        await self._pool.execute("DELETE FROM pgxnl_glossary WHERE id=$1", entry_id)
