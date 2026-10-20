"""Physical Lab — 스키마의 **물리 상태**를 본다. Design Lab 의 짝이다.

```
Design Lab     논리 구조   정규형 · 같은 개념의 사본 · 혼합 그레인
Physical Lab   물리 상태   차지하는 공간 · 죽은 행 · VACUUM · 안 쓰이는 인덱스
```

Design Lab 과 같은 규칙을 따른다 — **결정론적이고**(LLM 호출 없음) **읽기 전용**이며,
화면에서 스키마를 골라 요청할 때만 계산하고 캐시하지 않는다(카탈로그가 바뀌면 결과도
바뀐다).

## 통계 초기화 시점을 함께 돌려주는 이유

`idx_scan = 0` 은 "안 쓰이는 인덱스"가 **아니다.** `pg_stat_reset()` 이후의 횟수일
뿐이라, 어제 통계를 지웠으면 모든 인덱스가 0 으로 보인다. 그 숫자만 보고 인덱스를
지우면 멀쩡한 것을 지운다. 그래서 `stats_reset` 을 같이 내보내 화면이 함께 보여주게
한다 — 판정하지 않고 근거를 돌려주는 것은 `stats_guard` 와 같은 방침이다.

마찬가지로 `reltuples` 는 추정치다(마지막 ANALYZE 기준). 정확한 행 수가 필요하면
세어야 하는데, 큰 테이블에서 전수 COUNT 는 이 화면이 감당할 일이 아니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: 스키마 이름은 파라미터로 못 넘긴다(`execute_readonly` 가 파라미터를 받지 않는다).
#: 리터럴로 박아야 해서, 박기 전에 식별자 모양인지 확인한다.
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

#: 죽은 행이 이 비율을 넘으면 짚는다. VACUUM 기본 임계값(autovacuum_vacuum_scale_factor
#: 0.2)보다 넉넉히 잡았다 — 0.2 를 그대로 쓰면 정상 동작 중인 테이블까지 전부 걸린다.
_DEAD_PCT_HIGH = 30.0
_DEAD_PCT_MEDIUM = 10.0

#: 이 크기 아래의 인덱스는 안 쓰여도 짚지 않는다. 지워봐야 얻는 게 없고 목록만 길어진다.
_UNUSED_INDEX_MIN_BYTES = 1024 * 1024  # 1MB


@dataclass
class Finding:
    kind: str
    severity: str  # high | medium | info
    title: str
    detail: str
    action: str
    tables: list[str] = field(default_factory=list)


@dataclass
class PhysicalReport:
    target_name: str
    schema: str
    total_bytes: int
    stats_reset: Any
    tables: list[dict[str, Any]]
    bloat: list[dict[str, Any]]
    indexes: list[dict[str, Any]]
    findings: list[Finding]


def _lit(schema: str) -> str:
    if not _IDENT.match(schema):
        raise ValueError(f"스키마 이름 모양이 아닙니다: {schema!r}")
    return f"'{schema}'"


_SIZES = """
SELECT c.relname                                              AS table_name,
       pg_total_relation_size(c.oid)                          AS total_bytes,
       pg_relation_size(c.oid)                                AS heap_bytes,
       pg_indexes_size(c.oid)                                 AS index_bytes,
       COALESCE(pg_total_relation_size(c.reltoastrelid), 0)   AS toast_bytes,
       c.reltuples::bigint                                    AS est_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = {s} AND c.relkind IN ('r', 'p')
ORDER BY pg_total_relation_size(c.oid) DESC
"""

_BLOAT = """
SELECT relname AS table_name, n_live_tup, n_dead_tup,
       CASE WHEN n_live_tup + n_dead_tup > 0
            THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 1)
            ELSE 0 END                                        AS dead_pct,
       last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE schemaname = {s}
ORDER BY n_dead_tup DESC
"""

_INDEXES = """
SELECT s.relname                          AS table_name,
       s.indexrelname                     AS index_name,
       s.idx_scan,
       pg_relation_size(s.indexrelid)     AS bytes,
       i.indisunique                      AS is_unique,
       i.indisprimary                     AS is_primary
FROM pg_stat_user_indexes s
JOIN pg_index i ON i.indexrelid = s.indexrelid
WHERE s.schemaname = {s}
ORDER BY s.idx_scan ASC, pg_relation_size(s.indexrelid) DESC
"""

_RESET = "SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()"


def human_bytes(n: int | None) -> str:
    b = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or unit == "TB":
            return f"{b:.0f} {unit}" if unit == "B" else f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _findings(
    tables: list[dict[str, Any]], bloat: list[dict[str, Any]], indexes: list[dict[str, Any]],
) -> list[Finding]:
    out: list[Finding] = []

    for r in bloat:
        pct = float(r.get("dead_pct") or 0)
        if pct < _DEAD_PCT_MEDIUM or (r.get("n_dead_tup") or 0) < 1000:
            continue
        sev = "high" if pct >= _DEAD_PCT_HIGH else "medium"
        vac = r.get("last_autovacuum") or r.get("last_vacuum")
        out.append(Finding(
            kind="dead_tuples", severity=sev,
            title=f"{r['table_name']} — 죽은 행 {pct}%",
            detail=(f"살아있는 행 {r.get('n_live_tup'):,}개, 죽은 행 {r.get('n_dead_tup'):,}개. "
                    + (f"마지막 VACUUM {vac}." if vac else "VACUUM 기록이 없습니다.")),
            action="VACUUM 으로 회수할 수 있는 공간입니다. 반복되면 autovacuum 설정을 봅니다.",
            tables=[r["table_name"]],
        ))

    for r in indexes:
        if r.get("is_primary") or r.get("is_unique"):
            continue  # 제약을 받치는 인덱스다 — 안 쓰인다고 지울 수 있는 것이 아니다
        if (r.get("idx_scan") or 0) > 0 or (r.get("bytes") or 0) < _UNUSED_INDEX_MIN_BYTES:
            continue
        out.append(Finding(
            kind="unused_index", severity="medium",
            title=f"{r['index_name']} — 조회 0회, {human_bytes(r.get('bytes'))}",
            detail=(f"{r['table_name']} 의 인덱스인데 통계가 쌓인 뒤로 한 번도 안 쓰였습니다. "
                    "다만 이 횟수는 통계를 지운 시점부터의 것이라, 최근에 지웠다면 "
                    "멀쩡한 인덱스도 0 으로 보입니다."),
            action="위의 통계 초기화 시점을 먼저 확인하세요. 충분히 오래됐다면 삭제 후보입니다.",
            tables=[r["table_name"]],
        ))

    by_name = {t["table_name"]: t for t in tables}
    for name, t in by_name.items():
        heap, idx = t.get("heap_bytes") or 0, t.get("index_bytes") or 0
        if idx > heap and heap >= _UNUSED_INDEX_MIN_BYTES:
            out.append(Finding(
                kind="index_heavier_than_table", severity="info",
                title=f"{name} — 인덱스가 테이블보다 큽니다",
                detail=f"테이블 {human_bytes(heap)}, 인덱스 {human_bytes(idx)}.",
                action="정상일 수 있습니다(조회가 많은 테이블). 안 쓰이는 인덱스가 섞여 있는지 위 목록과 함께 보세요.",
                tables=[name],
            ))
    return out


async def analyze_physical(catalog: Any, *, target_name: str, schema: str) -> PhysicalReport:
    """`catalog` 은 `execute_readonly(sql, schema=...)` 를 가진 객체 — Orchestrator 를
    그대로 넘긴다(Design Lab 과 같은 방식)."""
    s = _lit(schema)

    async def q(sql: str) -> list[dict[str, Any]]:
        return await catalog.execute_readonly(
            sql.format(s=s), row_limit=2000, timeout_seconds=30, schema=schema
        )

    tables = await q(_SIZES)
    bloat = await q(_BLOAT)
    indexes = await q(_INDEXES)
    reset_rows = await q(_RESET)

    order = {"high": 0, "medium": 1, "info": 2}
    return PhysicalReport(
        target_name=target_name,
        schema=schema,
        total_bytes=sum(int(t.get("total_bytes") or 0) for t in tables),
        stats_reset=reset_rows[0]["stats_reset"] if reset_rows else None,
        tables=tables,
        bloat=bloat,
        indexes=indexes,
        findings=sorted(_findings(tables, bloat, indexes), key=lambda f: order[f.severity]),
    )
