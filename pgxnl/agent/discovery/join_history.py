"""pg_stat_statements 기반 실행이력 조인 발견. design 문서 §5.3 참고.

명시적 FK 제약이 없는 레거시 스키마에서, 실제로 자주 실행된 JOIN 쿼리로부터
암묵적 관계를 역추적한다. calls(누적 실행 횟수)를 신뢰도 가중치로 사용한다.
pg_stat_statements 확장과 pg_read_all_stats 권한이 필요하다. 기본 비활성
(PGXNL_JOIN_DISCOVERY_ENABLED).
"""
from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from pgxnl.parsing.base import SqlParser


@dataclass
class JoinCandidate:
    table_a: str
    column_a: str
    table_b: str
    column_b: str
    calls: int
    source: str = "history"


_INTERNAL_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}


def is_internal_table(qualified: str) -> bool:
    schema, _, table = qualified.rpartition(".")
    if schema:
        return schema.lower() in _INTERNAL_SCHEMAS
    return table.lower().startswith("pg_")


def references_only_internal(tables: list[str]) -> bool:
    """조회된 테이블이 모두 시스템 카탈로그(information_schema/pg_catalog/pg_*)뿐이면
    True — pgxnl 자신의 스키마 조회(describe_table 등)가 남긴 잡음이라 수집 대상에서 뺀다."""
    return bool(tables) and all(is_internal_table(t) for t in tables)


async def discover_joins_from_history(
    system_pool: asyncpg.Pool, parser: SqlParser, *, limit: int = 500
) -> list[JoinCandidate]:
    # 확장이 설치된 스키마를 찾아 **한정해서** 조회한다. 대상 DSN이 search_path를
    # 특정 스키마로 고정하는 경우(BIRD는 `options=-csearch_path=california_schools`)
    # public이 경로에서 빠져 `pg_stat_statements`를 못 찾는다 — 실측: 수집 API가
    # "relation does not exist"로 실패했고, 그래서 이 대상의 조인 후보가 하나도
    # 쌓이지 않았다(psql 기본 연결로는 같은 조회가 4,887행을 돌려준다).
    ext_schema = await system_pool.fetchval(
        """
        SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = 'pg_stat_statements'
        """
    )
    if not ext_schema:
        raise RuntimeError("pg_stat_statements 확장이 설치돼 있지 않습니다")
    rows = await system_pool.fetch(
        f"""
        SELECT query, calls FROM {ext_schema}.pg_stat_statements
        WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
          AND query ILIKE '%JOIN%'
          AND query NOT ILIKE '%information_schema%'
          AND query NOT ILIKE '%pg_catalog%'
          AND query NOT ILIKE '%pg_stat_statements%'
          AND query NOT ILIKE '%pgxnl\\_%' ESCAPE '\\'
        ORDER BY calls DESC LIMIT $1
        """,
        limit,
    )
    # (테이블A, 컬럼A, 테이블B, 컬럼B) -> 누적 calls. **정규화하지 않으면 같은 관계가
    # 표기 차이로 여러 행이 된다** — 실측: `frpm.CDSCode↔satscores.cds`(85회),
    # `frpm.cdscode↔satscores.cds`(4회), `satscores.cds↔frpm.cdscode`(10회)가 별개 행으로
    # 쌓여 신뢰도가 흩어졌다. 대소문자를 접고 방향을 정렬해 하나로 모은다.
    # 맨 테이블 이름에 스키마를 붙인다. 쿼리가 스키마를 명시했는지에 따라 `frpm`과
    # `california_schools.frpm`이 별개 행이 되던 것을 하나로 모은다. 이름이 여러 스키마에
    # 있으면 어느 쪽인지 알 수 없으므로 맨 이름 그대로 둔다(실측: BIRD의 77개 테이블은
    # 이름이 전부 유일해 모두 해소된다).
    catalog = await system_pool.fetch(
        """
        SELECT lower(table_name) AS t, lower(table_schema) AS s
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        """
    )
    schema_of: dict[str, str | None] = {}
    for r in catalog:
        schema_of[r["t"]] = None if r["t"] in schema_of else r["s"]  # 중복이면 None

    def qualify(name: str) -> str:
        low = name.lower()
        if "." in low:
            return low
        found = schema_of.get(low)
        return f"{found}.{low}" if found else low

    merged: dict[tuple[str, str, str, str], int] = {}
    for row in rows:
        try:
            parsed = parser.parse(row["query"])
        except Exception:  # noqa: BLE001 - 파싱 실패한 쿼리는 건너뛴다 (플레이스홀더 등 이슈)
            continue
        if not parsed.is_well_formed:
            # 문법 오류가 있으면 ANTLR이 복구하면서 트리 일부를 버려 joins/tables가
            # 불완전해진다 — 그걸로 조인 후보를 만들면 없는 관계를 학습한다.
            continue
        if references_only_internal(parsed.referenced_tables):
            continue
        for j in parsed.joins:
            if is_internal_table(j.table_a) or is_internal_table(j.table_b):
                continue
            a = (qualify(j.table_a), j.column_a.lower())
            b = (qualify(j.table_b), j.column_b.lower())
            if a[0] == b[0]:
                # 같은 테이블끼리는 조인 관계가 아니다. 별칭 해석이 어긋나거나
                # `WHERE s.school = f."School Name"` 같은 비교를 조인으로 읽은 경우다
                # (실측: schools.school ↔ schools."school name"이 후보로 올라왔다).
                continue
            # 방향을 정렬해 A↔B와 B↔A를 한 행으로 모은다. 조인은 대칭 관계다.
            first, second = (a, b) if a <= b else (b, a)
            key = (first[0], first[1], second[0], second[1])
            merged[key] = merged.get(key, 0) + row["calls"]

    return [
        JoinCandidate(table_a=ta, column_a=ca, table_b=tb, column_b=cb, calls=calls)
        for (ta, ca, tb, cb), calls in sorted(merged.items(), key=lambda kv: -kv[1])
    ]


async def persist_candidates(pool: asyncpg.Pool, target_name: str, candidates: list[JoinCandidate]) -> None:
    from pgxnl.agent.discovery.graph import edge_key

    for c in candidates:
        # confidence는 calls 기반 단순 정규화 예시. 실제로는 전체 calls 분포를 보고
        # 스케일링하는 것을 권장 (design 문서 §5절 3단 필터링과 결합 시 재조정).
        confidence = min(1.0, c.calls / 100)
        # 한정 이름(`schema.table`)이면 스키마를 떼어 schema_name 열로(2026-10-07). SQL 수집 경로는
        # 카탈로그 없이 SQL에 적힌 대로 들어오므로 맨 이름이면 schema_name='' 로 남는다.
        schema, ta, ca, tb, cb = edge_key("", c.table_a, c.column_a, c.table_b, c.column_b)
        await pool.execute(
            """
            INSERT INTO pgxnl_join_candidates
                (target_name, schema_name, table_a, column_a, table_b, column_b, source, confidence, calls)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (target_name, schema_name, table_a, column_a, table_b, column_b)
            DO UPDATE SET confidence = EXCLUDED.confidence, calls = EXCLUDED.calls
            """,
            target_name, schema, ta, ca, tb, cb, c.source, confidence, c.calls,
        )
