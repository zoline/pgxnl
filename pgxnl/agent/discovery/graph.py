"""JOIN 그래프 조회/경로탐색. pgxnl_join_candidates(§5.3)를 그래프 저장소로 재사용한다.

discovery/join_history.py가 실행이력에서 candidate를 채우고(source='history'),
agent/discovery/statements.py의 SQL 수집도 같은 테이블에 적재한다(source='collected').
이 모듈은 그 테이블을 읽어 그래프 질의(이웃, 최단경로)만 담당한다.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import asyncpg


@dataclass
class JoinEdge:
    id: int
    table_a: str
    column_a: str
    table_b: str
    column_b: str
    source: str
    confidence: float
    calls: int | None
    reviewed: bool
    #: 두 테이블이 속한 스키마. '' = 미상(2026-10-07 schema_name 열 도입 전 데이터 중 카탈로그로
    #: 못 정한 것). table_a/table_b 는 맨 이름이다.
    schema_name: str = ""

    def qualified(self, table: str) -> str:
        return f"{self.schema_name}.{table}" if self.schema_name else table


_EDGE_COLS = "id, table_a, column_a, table_b, column_b, source, confidence, calls, reviewed, schema_name"


@dataclass
class JoinPath:
    tables: list[str] = field(default_factory=list)
    edges: list[JoinEdge] = field(default_factory=list)

    @property
    def hops(self) -> int:
        return len(self.edges)


async def list_edges(
    pool: asyncpg.Pool, target_name: str, *, only_reviewed: bool = False, schema: str | None = None,
) -> list[JoinEdge]:
    """`schema`를 주면 그 스키마의 관계와 스키마 미상('') 관계만 — 미상은 맨 이름으로 맞춰 본다."""
    conditions = ["target_name = $1"]
    params: list = [target_name]
    if only_reviewed:
        conditions.append("reviewed = true")
    if schema is not None:
        params.append(schema.lower())
        conditions.append(f"schema_name IN (${len(params)}, '')")
    order = "confidence DESC" if only_reviewed else "reviewed DESC, confidence DESC"
    rows = await pool.fetch(
        f"SELECT {_EDGE_COLS} FROM pgxnl_join_candidates WHERE {' AND '.join(conditions)} "
        f"ORDER BY schema_name, {order}",
        *params,
    )
    return [JoinEdge(**dict(r)) for r in rows]


async def approve_edges(pool: asyncpg.Pool, target_name: str, ids: list[int]) -> int:
    rows = await pool.fetch(
        "UPDATE pgxnl_join_candidates SET reviewed = true WHERE target_name = $1 AND id = ANY($2::int[]) RETURNING id",
        target_name, ids,
    )
    return len(rows)


async def unapprove_edges(pool: asyncpg.Pool, target_name: str, ids: list[int]) -> int:
    """승인을 해제해 후보(대기) 상태로 되돌린다 — 행은 지우지 않는다. 실행 이력으로 쌓인 근거(calls,
    출처)를 잃지 않고 다시 검토할 수 있게. 거부(reject_edges)는 행을 삭제한다(2026-10-12)."""
    rows = await pool.fetch(
        "UPDATE pgxnl_join_candidates SET reviewed = false WHERE target_name = $1 AND id = ANY($2::int[]) "
        "AND reviewed RETURNING id",
        target_name, ids,
    )
    return len(rows)


async def reject_edges(pool: asyncpg.Pool, target_name: str, ids: list[int]) -> int:
    rows = await pool.fetch(
        "DELETE FROM pgxnl_join_candidates WHERE target_name = $1 AND id = ANY($2::int[]) RETURNING id",
        target_name, ids,
    )
    return len(rows)


def normalize_ref(table: str, column: str) -> tuple[str, str]:
    """조인 관계의 표기를 하나로 맞춘다: 둘 다 소문자, 따옴표 제거.

    표기가 섞이면 **같은 관계가 여러 행이 된다** — 실측: `frpm.CDSCode↔satscores.cds`,
    `frpm.cdscode↔satscores.cds`, `california_schools.frpm.cdscode↔...`가 별개로 쌓여
    신뢰도가 흩어졌다(487건 -> 정규화 후 17건). 저장·조회 양쪽에서 이 함수를 통과시킨다.
    스키마는 `split_schema()`로 떼어 schema_name 열에 둔다(2026-10-07).
    """
    return table.strip().strip('"').lower(), column.strip().strip('"').lower()


def split_schema(table: str) -> tuple[str, str]:
    """`schema.table` -> (schema, table). 스키마가 없으면 ('', table). 소문자·따옴표 제거."""
    low = table.strip().replace('"', "").lower()
    schema, _, bare = low.rpartition(".")
    return schema, bare


def edge_key(schema_name: str, table_a: str, column_a: str, table_b: str, column_b: str) -> tuple[str, ...]:
    """저장 키 하나로 맞춘다 — 스키마를 떼고(인자 schema_name 이 우선, 없으면 이름에서), 방향을
    정렬해 A↔B와 B↔A를 한 행으로 모은다(조인은 대칭이다). 양쪽 스키마가 다르면 한정 이름을
    그대로 두고 schema_name='' 로 둔다(스키마를 넘나드는 관계 — 2026-10-07 0건)."""
    sa, ta = split_schema(table_a)
    sb, tb = split_schema(table_b)
    schema = (schema_name or "").strip().lower() or sa or sb
    if (sa and sa != schema) or (sb and sb != schema):
        schema = ""
        ta, tb = table_a.strip().replace('"', "").lower(), table_b.strip().replace('"', "").lower()
    a = (ta, column_a.strip().strip('"').lower())
    b = (tb, column_b.strip().strip('"').lower())
    if a > b:
        a, b = b, a
    return schema, a[0], a[1], b[0], b[1]


async def add_manual_edge(
    pool: asyncpg.Pool, target_name: str, table_a: str, column_a: str, table_b: str, column_b: str,
    *, source: str = "manual", schema_name: str = "",
) -> JoinEdge:
    """사람이 단언한 JOIN 관계. 별도 승인 없이 바로 reviewed=true로 등록한다.

    `source` 기본값은 'manual'(관리 화면에서 직접 등록) — 실행이력 기반 후보와
    섞이지 않게 구분한다. Design Lab의 "단계별 3NF 적용" 마법사는 다른 값
    ('design_proposal')을 넘긴다 — 그 관계가 가리키는 테이블(룩업 테이블)은
    **아직 실제로 존재하지 않는다**(마법사는 시뮬레이션만 하고 DDL을 실행하지
    않는다). 같은 'manual'로 넣으면 실제 등록된 관계와 구분이 안 돼, 나중에
    JOIN 그래프에서 존재하지 않는 테이블을 가리키는 오염 데이터가 된다(실측:
    2026-09-15 dvdrental 사례와 같은 종류)."""
    # 수집 경로(join_history)와 같은 정규화를 적용한다 — 한쪽만 정규화하면 수동 등록이
    # 중복 행을 만든다(edge_key: 스키마 분리 + 방향 정렬).
    schema, ta, ca, tb, cb = edge_key(schema_name, table_a, column_a, table_b, column_b)
    row = await pool.fetchrow(
        f"""
        INSERT INTO pgxnl_join_candidates
            (target_name, schema_name, table_a, column_a, table_b, column_b, source, confidence, calls, reviewed)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 1.0, NULL, true)
        ON CONFLICT (target_name, schema_name, table_a, column_a, table_b, column_b)
        DO UPDATE SET reviewed = true, source = $7, confidence = 1.0
        RETURNING {_EDGE_COLS}
        """,
        target_name, schema, ta, ca, tb, cb, source,
    )
    return JoinEdge(**dict(row))


async def backfill_schema_names(pool: asyncpg.Pool, target_name: str, schema_of: dict[str, str | None]) -> dict:
    """스키마 미상('') 행을 카탈로그로 채운다. `schema_of`: 맨 테이블 이름(소문자) -> 스키마,
    여러 스키마에 같은 이름이 있으면 None. 두 테이블 중 **존재하는 쪽**으로 정한다 — Design Lab
    제안은 룩업 테이블이 아직 없어서(시뮬레이션) 한쪽만 카탈로그에 있다. 양쪽이 다른 스키마로
    갈리거나 아무 쪽도 못 정하면 그대로 둔다. 같은 키의 행이 이미 있으면(중복) 건너뛴다."""
    rows = await pool.fetch(
        "SELECT id, table_a, table_b FROM pgxnl_join_candidates WHERE target_name = $1 AND schema_name = ''",
        target_name,
    )
    filled, skipped = [], []
    for r in rows:
        if "." in r["table_a"] or "." in r["table_b"]:
            skipped.append(r["id"])
            continue
        found = {schema_of.get(r["table_a"]), schema_of.get(r["table_b"])} - {None}
        if len(found) != 1:
            skipped.append(r["id"])
            continue
        try:
            await pool.execute("UPDATE pgxnl_join_candidates SET schema_name = $1 WHERE id = $2", found.pop(), r["id"])
            filled.append(r["id"])
        except asyncpg.UniqueViolationError:
            skipped.append(r["id"])
    return {"filled": filled, "skipped": skipped}


async def find_path(
    pool: asyncpg.Pool, target_name: str, from_table: str, to_table: str, max_hops: int = 5,
    *, schema: str | None = None,
) -> JoinPath | None:
    """승인된(reviewed=true) JOIN만으로 경로를 찾는다 — 검토되지 않은 후보는 신뢰할 수
    없어 경로 탐색/그래프 확정에는 쓰지 않는다(§ 승인 워크플로). 노드는 `schema.table`
    (스키마 미상이면 맨 이름)이다 — 다른 스키마의 같은 이름 테이블이 한 노드로 섞이지 않게."""
    stored = await list_edges(pool, target_name, only_reviewed=True, schema=schema)
    edges = [
        JoinEdge(e.id, e.qualified(e.table_a), e.column_a, e.qualified(e.table_b), e.column_b,
                 e.source, e.confidence, e.calls, e.reviewed, e.schema_name)
        for e in stored
    ]

    # 호출자가 맨 이름으로 물어도 찾히도록, 노드 중 끝 조각이 일치하는 것으로 해석한다.
    known = {e.table_a for e in edges} | {e.table_b for e in edges}

    def resolve(name: str) -> str:
        low = name.strip().strip('"').lower()
        if low in known:
            return low
        matches = [k for k in known if k.rsplit(".", 1)[-1] == low]
        return matches[0] if len(matches) == 1 else low

    from_table, to_table = resolve(from_table), resolve(to_table)
    if from_table == to_table:
        return JoinPath(tables=[from_table])
    adjacency: dict[str, list[JoinEdge]] = {}
    for e in edges:
        adjacency.setdefault(e.table_a, []).append(e)
        adjacency.setdefault(e.table_b, []).append(
            JoinEdge(e.id, e.table_b, e.column_b, e.table_a, e.column_a, e.source, e.confidence, e.calls, e.reviewed,
                     e.schema_name)
        )

    queue: deque[tuple[str, list[JoinEdge], list[str]]] = deque([(from_table, [], [from_table])])
    visited = {from_table}
    while queue:
        current, path_edges, path_tables = queue.popleft()
        if len(path_edges) >= max_hops:
            continue
        for edge in adjacency.get(current, []):
            neighbor = edge.table_b
            if neighbor in visited:
                continue
            new_edges = path_edges + [edge]
            new_tables = path_tables + [neighbor]
            if neighbor == to_table:
                return JoinPath(tables=new_tables, edges=new_edges)
            visited.add(neighbor)
            queue.append((neighbor, new_edges, new_tables))
    return None


async def delete_target(pool: asyncpg.Pool, target_name: str) -> int:
    rows = await pool.fetch("DELETE FROM pgxnl_join_candidates WHERE target_name = $1 RETURNING id", target_name)
    return len(rows)


def _bare(qualified: str) -> str:
    return qualified.rsplit(".", 1)[-1].strip('"').lower()


def _edge_matches(joins: list, table_a: str, column_a: str, table_b: str, column_b: str) -> bool:
    """SQL 하나가 실제로 이 엣지를 쓰는지 — `parsed.joins`(ANTLR 파서가 그 SQL에서
    뽑은 JOIN 조건들)를 이 엣지의 (테이블, 컬럼) 쌍과 맞춰본다.

    스키마 한정 여부는 무시하고 맨 이름으로만 비교한다 — `pgxnl_sql_statements`에
    이미 `public.actor`와 맨 `actor`가 섞여 들어와 있고(수집 경로가 여럿이라
    한정 방식이 다르다, 실측 확인), 스키마까지 맞추려면 이 엣지 쪽도 늘 한정돼
    있어야 하는데 그렇지 않다. 조인은 대칭이라 방향도 양쪽 다 본다."""
    want = {(_bare(table_a), column_a.lower()), (_bare(table_b), column_b.lower())}
    for j in joins:
        got = {(_bare(j.table_a), j.column_a.lower()), (_bare(j.table_b), j.column_b.lower())}
        if got == want:
            return True
    return False


@dataclass
class EdgeStatement:
    sql_text: str
    call_count: int | None
    source: str
    confirmed: bool  # True면 파서가 이 엣지를 정확히 확인, False면 두 테이블만 같이 나옴(참고용)
    question: str | None = None  # pgxnl_verified_queries 출처면 등록된 질문, 아니면 None


async def find_statements_for_edge(
    pool: asyncpg.Pool, parser, target_name: str, table_a: str, column_a: str, table_b: str, column_b: str,
    *, limit: int = 2000,
) -> list[EdgeStatement]:
    """이 JOIN 엣지가 실제로 어떤 SQL에서 나왔는지 찾는다.

    `pgxnl_join_candidates`는 집계(테이블A.컬럼A = 테이블B.컬럼B, 누적 calls)만
    갖고 있고 어느 SQL에서 왔는지는 남기지 않는다 — 그래서 저장된 값을 조회하는
    대신, 매번 `pgxnl_sql_statements`를 다시 훑어 파서로 확인한다. 코드 변경 없이
    기존 데이터에도 바로 쓸 수 있는 이유다.

    두 단계로 거른다: ① `tables_used`에 두 테이블이 같이 있는지(가벼움, 대부분을
    걸러낸다) ② 그중에서 실제로 파싱해 이 (테이블,컬럼) 쌍으로 조인하는지
    (`_edge_matches`) — ①만 통과하고 ②를 통과 못 하면 "두 테이블을 같이 쓰지만
    이 컬럼으로 조인하는지는 확인 안 됨"으로 표시한다(`confirmed=False`).
    """
    ba, bb = _bare(table_a), _bare(table_b)

    def check(sql_text: str) -> bool:
        try:
            parsed = parser.parse(sql_text)
            return bool(parsed.is_well_formed and _edge_matches(parsed.joins, table_a, column_a, table_b, column_b))
        except Exception:  # noqa: BLE001 — 확인 실패는 "참고용"으로 내려간다, 오류로 막지 않는다
            return False

    out: list[EdgeStatement] = []

    rows = await pool.fetch(
        "SELECT sql_text, call_count, source, tables_used FROM pgxnl_sql_statements "
        "WHERE target_name = $1 ORDER BY call_count DESC LIMIT $2",
        target_name, limit,
    )
    for r in rows:
        used = {_bare(t) for t in (r["tables_used"] or [])}
        if ba not in used or bb not in used:
            continue
        out.append(EdgeStatement(
            sql_text=r["sql_text"], call_count=r["call_count"], source=r["source"], confirmed=check(r["sql_text"]),
        ))

    # 사람이 승인한 사용례도 같이 본다 — 실제 수집 SQL만큼 신뢰할 만하고(승인
    # 절차를 거쳤다), 질문 문장이 붙어 있어 "왜 이 조인이 필요한가"까지 보여준다.
    vq_rows = await pool.fetch(
        "SELECT question, sql_text, tables_used FROM pgxnl_verified_queries "
        "WHERE target_name = $1 AND approved ORDER BY created_at DESC LIMIT $2",
        target_name, limit,
    )
    for r in vq_rows:
        used = {_bare(t) for t in (r["tables_used"] or [])}
        if ba not in used or bb not in used:
            continue
        out.append(EdgeStatement(
            sql_text=r["sql_text"], call_count=None, source="verified", confirmed=check(r["sql_text"]),
            question=r["question"],
        ))

    # 확인된 것을 먼저, 그다음 호출 많은 순(이미 SQL로 정렬돼 들어왔으니 안정 정렬로 유지된다)
    out.sort(key=lambda s: not s.confirmed)
    return out
