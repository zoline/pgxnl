"""후보를 **데이터로 검증**해 실제 위반만 남긴다.

`detect`가 이름만 보고 만든 후보를 대상 DB에 물어 확인한다. 핵심 원칙:

**"위반"이 아니라 "답이 갈리는 것"만 보고한다.** 실측(BIRD `california_schools`)에서
`county`는 3개 테이블에 중복이지만 값 불일치가 0%였다 — 어느 사본을 써도 결과가
같으므로 경고하면 소음이다. 반대로 `school name`은 2.5~4.5%가 갈려서, 30문항 중
12개가 그 컬럼을 쓰는 상황에서 모델이 정답 논리를 알아도 틀리게 만든다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from pgxnl.agent.designlab.detect import (
    find_code_name_pairs,
    find_duplicate_concepts,
    find_repeating_groups,
)

#: 사본이 이 비율을 넘게 갈리면 질의 결과까지 달라질 수 있어 심각도를 올린다.
#: **그 아래라고 정상은 아니다** — 같아야 할 값이 하나라도 다르면 정합성 결함이다
#: (`schools.charternum` ↔ `frpm."Charter School Number"`는 1,167행 중 1행만
#: 다른데, 그 1행은 "의미 차이"가 아니라 명백한 데이터 오류다). 0%만 정상으로 본다.
HIGH_DIVERGENCE_PCT = 2.0

#: 양쪽 다 값이 있는 행이 이 수보다 적으면 불일치율이 의미 없다.
MIN_COMPARABLE_ROWS = 50

#: **이 비율을 넘으면 애초에 같은 개념이 아니다.** 같은 이름을 우연히 공유할 뿐이다 —
#: `card_games`의 6개 테이블에 있는 `id`, `financial`의 3개 테이블에 있는 `date`
#: (계좌개설일/거래일/대출일)가 100% 불일치로 보고됐다. 진짜 사본은 **대부분
#: 일치하면서 일부만 어긋난다**(학교명 2.5%, 5.8%). 완전히 다르면 중복이 아니라
#: 동명이인이다. 이름만으로 개념을 묶는 한계를 데이터로 걸러내는 장치다.
MAX_DIVERGENCE_PCT = 40.0

#: 한 쌍을 비교할 때 읽는 최대 행 수. 큰 테이블에서 전수 비교는 비싸다.
SAMPLE_LIMIT = 200_000

#: 이름/식별 컬럼으로 볼 이름 패턴. 이 컬럼이 비면 그 행은 다른 종류의 개체다.
_IDENTITY_COLUMN = re.compile(r"(?:^|_|\s)(?:name|nm|title|label)$|^s?name$", re.IGNORECASE)

#: 파티션이 이 비율(전체 행 대비)보다 작으면 판정에서 제외한다. 4행짜리 파티션에서
#: 어떤 컬럼이 전부 NULL인 것은 통계적으로 의미가 없다 — 초기 구현에서
#: `frpm."District Type"='Non-School Locations'`(4행) 같은 것이 무더기로 잡혔다.
MIN_PARTITION_RATIO = 0.05
#: 비율과 별개로 요구하는 절대 행 수.
MIN_PARTITION_ROWS = 100

#: 구분 컬럼(discriminator) 후보로 볼 고유값 개수의 상한. 'S'/'D' 같은 종류 표시는
#: 값이 적다 — 너무 크게 잡으면 모든 저카디널리티 컬럼이 후보가 되어 질의가 늘어난다.
MAX_DISCRIMINATOR_VALUES = 8

#: 코드의 고유값이 행 수의 이 비율을 넘으면 그 컬럼은 사실상 키다. 키는 **모든**
#: 컬럼을 함수적으로 결정하므로 이행 종속이라 부를 게 없다 — 실측에서
#: `frpm."School Code"`(9,942종/9,986행)가 School Name/Type을 결정한다고 보고돼
#: 소음이 됐다. 의미 있는 이행 종속은 코드 종류가 적다(soc 21종, doc 12종).
KEYLIKE_DISTINCT_RATIO = 0.9


class Catalog(Protocol):
    """Design Lab이 대상 DB에 요구하는 최소 인터페이스 (`PgConnector`가 만족한다)."""

    async def list_tables(self, schema: str) -> list[Any]: ...
    async def describe_table(self, schema: str, table: str) -> Any: ...
    async def execute_readonly(
        self, sql: str, *, row_limit: int, timeout_seconds: int, schema: str
    ) -> list[dict]: ...


@dataclass(frozen=True)
class Finding:
    """사용자에게 보여줄 진단 한 건."""

    kind: str          # "repeating_group" | "transitive_dependency" | "duplicate_concept"
    normal_form: str   # "1NF" | "2NF" | "3NF"
    severity: str      # "high" | "medium" | "info"
    title: str
    detail: str
    #: 지금 당장 할 수 있는 대응 (마이그레이션이 아니라 NL2SQL 대응책)
    action: str
    tables: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepeatingGroup:
    table: str
    base: str
    columns: list[str]


@dataclass(frozen=True)
class TransitiveDependency:
    table: str
    code_column: str
    name_column: str
    distinct_codes: int


@dataclass(frozen=True)
class MixedGrain:
    """한 테이블에 서로 다른 종류의 개체가 섞여 있는 경우.

    구분 컬럼(discriminator)의 값에 따라 어떤 컬럼이 통째로 NULL이 된다 —
    실측: `satscores.rtype`이 'S'(학교 1,749행)와 'D'(교육구 520행)를 가르고,
    'D' 행은 `sname`이 전부 NULL이다.
    """

    table: str
    discriminator: str
    #: 구분값 -> (행 수, 그 값에서 통째로 NULL인 컬럼들)
    partitions: list[tuple[str, int, list[str]]]


@dataclass(frozen=True)
class DivergenceCause:
    """불일치가 왜 생겼는지 — 정합성 결함은 원인을 알아야 고칠 수 있다.

    실측(`satscores.sname` ↔ `schools.school`): 102건 중 53건이 한쪽이 다른 쪽의
    접두사이고 그중 46건은 **정확히 50자에서 잘렸다.** 의미 차이가 아니라 적재 과정의
    길이 제한이다. 이런 원인이 보이면 "어느 컬럼을 쓸지 정하라"가 아니라 "데이터를
    고쳐라"가 옳은 조치다.
    """

    total: int
    diff: int
    case_only: int       # 대소문자만 다름
    space_only: int      # 앞뒤 공백만 다름
    prefix: int          # 한쪽이 다른 쪽의 접두사 (절단 의심)
    truncated_50: int    # 그중 정확히 50자에서 잘린 것


@dataclass(frozen=True)
class DuplicateConcept:
    concept: str
    columns: list[tuple[str, str]]
    #: (테이블A.컬럼A, 테이블B.컬럼B, 비교행수, 불일치행수, 불일치율%)
    divergences: list[tuple[str, str, int, int, float]]
    #: "테이블A.컬럼A ↔ 테이블B.컬럼B" -> 불일치 원인 분류
    causes: dict[str, DivergenceCause] = field(default_factory=dict)
    #: 값이 갈릴 때 "정본"으로 삼을 후보 — FK가 참조하는 부모 테이블.
    canonical: str | None = None


@dataclass
class SchemaReport:
    target_name: str
    schema: str
    tables: list[str]
    repeating_groups: list[RepeatingGroup] = field(default_factory=list)
    mixed_grains: list[MixedGrain] = field(default_factory=list)
    #: (테이블, 컬럼) -> 고유값 개수. 혼합 단위 탐색이 어차피 세므로 재질의 없이
    #: 남겨둔다 — 용어집 제안(suggest.py)이 "값을 나열할 만한 분류 컬럼"을 고를 때 쓴다.
    distinct_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    transitive_dependencies: list[TransitiveDependency] = field(default_factory=list)
    duplicate_concepts: list[DuplicateConcept] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    #: 데이터 검증을 건너뛴 이유(연결 실패 등). 비어 있으면 전부 확인했다는 뜻.
    skipped: list[str] = field(default_factory=list)


def _q(name: str) -> str:
    """식별자를 항상 큰따옴표로 감싼다 — `"School Name"`처럼 공백/대문자가 흔하다."""
    return '"' + name.replace('"', '""') + '"'


async def _scalar(conn: Catalog, schema: str, sql: str) -> dict | None:
    rows = await conn.execute_readonly(sql, row_limit=1, timeout_seconds=120, schema=schema)
    return dict(rows[0]) if rows else None


async def analyze_schema(
    conn: Catalog, *, target_name: str, schema: str,
    concept_aliases: dict[str, str] | None = None,
) -> SchemaReport:
    """한 스키마를 검토해 리포트를 만든다. LLM 호출 없음, 읽기 전용 SQL만 사용한다."""
    metas = [await conn.describe_table(schema, t.name) for t in await conn.list_tables(schema)]
    columns_by_table = {m.name: [c.name for c in m.columns] for m in metas}
    report = SchemaReport(target_name=target_name, schema=schema,
                          tables=sorted(columns_by_table))

    # 부모 테이블(= FK가 참조하는 쪽) 목록 — 중복 개념의 "정본" 판정에 쓴다.
    referenced: set[str] = {ref_table for m in metas for _, ref_table, _ in m.foreign_keys}
    join_keys = _join_keys(metas)

    await _collect_repeating_groups(report, columns_by_table)
    await _collect_mixed_grains(report, conn, schema, columns_by_table)
    await _collect_transitive_dependencies(report, conn, schema, columns_by_table)
    await _collect_duplicate_concepts(
        report, conn, schema, columns_by_table, referenced, join_keys, concept_aliases
    )
    return report


def _join_keys(metas: list[Any]) -> dict[tuple[str, str], tuple[str, str]]:
    """(테이블A, 테이블B) -> (컬럼A, 컬럼B). FK에서 조인 경로를 뽑는다."""
    keys: dict[tuple[str, str], tuple[str, str]] = {}
    for m in metas:
        for local, ref_table, ref_col in m.foreign_keys:
            keys[(m.name, ref_table)] = (local, ref_col)
            keys[(ref_table, m.name)] = (ref_col, local)
    return keys


async def _collect_repeating_groups(
    report: SchemaReport, columns_by_table: dict[str, list[str]]
) -> None:
    for cand in find_repeating_groups(columns_by_table):
        report.repeating_groups.append(
            RepeatingGroup(table=cand.table, base=cand.base, columns=cand.columns)
        )
        report.findings.append(Finding(
            kind="repeating_group", normal_form="1NF", severity="info",
            title=f"{cand.table}: 반복 그룹 {cand.base}* ({len(cand.columns)}개 컬럼)",
            detail=f"같은 속성이 번호를 달고 여러 컬럼으로 펼쳐져 있습니다: "
                   f"{', '.join(cand.columns)}. 1NF는 반복 그룹을 별도 테이블의 여러 행으로 "
                   f"두기를 요구합니다.",
            action="자연어 질문은 보통 '몇 번째'를 지정하지 않으므로 어느 컬럼을 볼지 "
                   "모호합니다. 질문에서 자주 쓰는 컬럼이 정해져 있다면 용어집에 "
                   "등록하세요.",
            tables=[cand.table], columns=cand.columns,
        ))


async def _collect_mixed_grains(
    report: SchemaReport, conn: Catalog, schema: str, columns_by_table: dict[str, list[str]]
) -> None:
    """구분 컬럼에 따라 다른 종류의 개체가 섞인 테이블을 찾는다.

    실측(BIRD `satscores`): `rtype='S'`는 학교 1,749행, `rtype='D'`는 교육구 520행이고
    'D' 행은 `sname`이 전부 NULL이다. **`numtsttakr` 합계가 209,913 vs 419,987로
    정확히 2배** — 교육구 행이 소속 학교를 이미 집계하고 있어서, 구분 없이 합치면
    모든 값을 두 번 센다.

    자연어 질문은 보통 "학교"를 뜻하지만 구분 컬럼을 언급하지 않으므로, 모델이
    필터를 넣을 근거가 없다. **자동으로 필터를 넣어서도 안 된다** — 실측에서 BIRD
    gold 13문항 전부 `rtype` 필터가 없어, 임의로 넣으면 오히려 기준 답과 어긋난다.
    알려주고 사용자가 정하게 한다.

    구분 컬럼마다 질의 하나로 모든 컬럼의 non-NULL 개수를 한 번에 센다 —
    컬럼 쌍을 도는 방식은 질의 수가 폭발한다.
    """
    seen_shapes: set[tuple] = set()
    for table, columns in columns_by_table.items():
        counts = ", ".join(f"count(DISTINCT {_q(c)}) AS {_q(c)}" for c in columns)
        try:
            row = await _scalar(conn, schema, f"SELECT {counts} FROM {_q(schema)}.{_q(table)}")
        except Exception as exc:  # noqa: BLE001
            report.skipped.append(f"{table} 구분 컬럼 탐색: {type(exc).__name__}")
            continue
        if not row:
            continue
        for c in columns:
            report.distinct_counts[(table, c)] = row.get(c) or 0
        candidates = [c for c in columns if 2 <= (row.get(c) or 0) <= MAX_DISCRIMINATOR_VALUES]

        for disc in candidates:
            others = [c for c in columns if c != disc]
            if not others:
                continue
            sel = ", ".join(f"count({_q(c)}) AS {_q(c)}" for c in others)
            sql = (f"SELECT {_q(disc)} AS _v, count(*) AS _n, {sel} "
                   f"FROM {_q(schema)}.{_q(table)} GROUP BY 1 ORDER BY 2 DESC")
            try:
                rows = await conn.execute_readonly(
                    sql, row_limit=MAX_DISCRIMINATOR_VALUES + 1, timeout_seconds=120, schema=schema
                )
            except Exception as exc:  # noqa: BLE001
                report.skipped.append(f"{table}.{disc}: {type(exc).__name__}")
                continue

            total = sum(dict(r)["_n"] for r in rows)
            floor = max(MIN_PARTITION_ROWS, total * MIN_PARTITION_RATIO)
            partitions = [
                (str(dict(r)["_v"]), dict(r)["_n"],
                 sorted(c for c in others if dict(r)[c] == 0))
                for r in rows
                if dict(r)["_n"] >= floor          # 작은 파티션은 통계적으로 무의미
            ]
            # 어떤 값에서는 통째로 NULL이고 다른 값에서는 채워진 컬럼이 있어야 "섞임"이다.
            split = {c for _, _, empty in partitions for c in empty}
            split = {c for c in split if any(c not in empty for _, _, empty in partitions)}
            if not split or len(partitions) < 2:
                continue
            # 상관된 구분 컬럼(eilcode/eilname처럼 1:1)은 **같은 분할**을 만든다 —
            # 파티션 크기만 보고 중복을 판정한다. NULL 컬럼 목록으로 비교하면 서로를
            # 목록에 넣기 때문에 다른 것으로 보여 두 번 보고된다.
            shape_key = (table, tuple(n for _, n, _ in partitions))
            if shape_key in seen_shapes:
                continue
            seen_shapes.add(shape_key)
            report.mixed_grains.append(MixedGrain(
                table=table, discriminator=disc, partitions=partitions,
            ))
            shape = "; ".join(f"{v}={n}행" for v, n, _ in partitions)
            # 이름/식별 컬럼이 비면 "그 행은 다른 종류의 개체"라는 뜻이라 훨씬 심각하다
            # (satscores의 'D' 행은 sname이 없다 = 학교가 아니라 교육구다). 그 외에는
            # "부류에 따라 없을 수 있는 선택적 속성"이라 정보 수준으로 낮춘다.
            identity = sorted(c for c in split if _IDENTITY_COLUMN.search(c))
            severity = "high" if identity else "info"
            if identity:
                detail = (f"{', '.join(identity)} 컬럼이 일부 '{disc}' 값에서 통째로 "
                          f"NULL입니다 — **이름이 없는 행은 다른 종류의 개체**라는 뜻입니다"
                          f"(예: 학교 행과 교육구 행, 질문 행과 답변 행). 구분 없이 세면 "
                          f"질문이 뜻하지 않은 행까지 포함되고, 상위 단위 행이 하위 단위를 "
                          f"이미 합산하고 있다면 값이 중복으로 계산됩니다.")
                action = (f"이 테이블을 집계하는 질문은 '{disc}' 필터가 없으면 값이 부풀 수 "
                          f"있습니다. 다만 **자동으로 필터를 넣지 마세요** — 어느 단위를 "
                          f"묻는지는 질문마다 다르고, 기준 답이 구분하지 않을 수도 있습니다"
                          f"(실측: BIRD gold 13문항 전부 rtype 필터가 없다).")
            else:
                detail = (f"{', '.join(sorted(split))} 컬럼이 일부 '{disc}' 값에서 통째로 "
                          f"NULL입니다 — 부류에 따라 존재하지 않는 선택적 속성입니다.")
                action = (f"이 컬럼들을 조건에 쓰는 질문은 '{disc}'가 다른 행을 자동으로 "
                          f"제외하게 됩니다. 의도한 것인지 확인하세요.")
            report.findings.append(Finding(
                kind="mixed_grain", normal_form="1NF", severity=severity,
                title=f"{table}: '{disc}' 값에 따라 비어 있는 컬럼이 다릅니다 ({shape})",
                detail=detail, action=action,
                tables=[table], columns=[disc, *sorted(split)],
            ))


async def _collect_transitive_dependencies(
    report: SchemaReport, conn: Catalog, schema: str, columns_by_table: dict[str, list[str]]
) -> None:
    for cand in find_code_name_pairs(columns_by_table):
        code, name, table = cand.code_column, cand.name_column, cand.table
        sql = (f"SELECT count(*) AS codes, count(*) FILTER (WHERE n > 1) AS violated, "
               f"sum(rows) AS total FROM "
               f"(SELECT {_q(code)} AS c, count(DISTINCT {_q(name)}) AS n, count(*) AS rows "
               f" FROM {_q(schema)}.{_q(table)} GROUP BY 1) t")
        try:
            row = await _scalar(conn, schema, sql)
        except Exception as exc:  # noqa: BLE001 — 조회 실패는 판단 불가
            report.skipped.append(f"{table}.{code}->{name}: {type(exc).__name__}")
            continue
        # violated > 0 이면 코드가 이름을 결정하지 못한다 = 이행 종속이 아니다.
        if not row or row["violated"]:
            continue
        # 코드가 사실상 키면 자명하게 모든 컬럼을 결정한다 — 보고할 게 없다.
        total = row["total"] or 0
        if total and row["codes"] / total > KEYLIKE_DISTINCT_RATIO:
            continue
        report.transitive_dependencies.append(TransitiveDependency(
            table=table, code_column=code, name_column=name, distinct_codes=row["codes"],
        ))
        report.findings.append(Finding(
            kind="transitive_dependency", normal_form="3NF", severity="info",
            title=f"{table}: {code} -> {name} 이행 종속 (코드 {row['codes']}종)",
            detail=f"{code} 값이 {name}을(를) 함수적으로 결정합니다(데이터로 확인). "
                   f"3NF는 이런 코드-이름 쌍을 별도 참조 테이블로 두기를 요구합니다.",
            action=f"질문이 이름('{name}')으로 물어도 모델이 코드('{code}')로 필터할 수 "
                   f"있고 그 반대도 마찬가지입니다. 코드-값 매핑을 용어집에 "
                   f"'Values: 코드=이름, ...' 형태로 등록하면 양쪽을 오갈 수 있습니다.",
            tables=[table], columns=[code, name],
        ))


async def _collect_duplicate_concepts(
    report: SchemaReport, conn: Catalog, schema: str, columns_by_table: dict[str, list[str]],
    referenced: set[str], join_keys: dict[tuple[str, str], tuple[str, str]],
    concept_aliases: dict[str, str] | None,
) -> None:
    for cand in find_duplicate_concepts(columns_by_table, aliases=concept_aliases):
        divergences: list[tuple[str, str, int, int, float]] = []
        causes: dict[str, DivergenceCause] = {}
        for i, (ta, ca) in enumerate(cand.columns):
            for tb, cb in cand.columns[i + 1:]:
                key = join_keys.get((ta, tb))
                if key is None:
                    continue  # 조인 경로를 모르면 비교할 수 없다
                ka, kb = key
                # **양쪽 다 값이 있는 행만 센다.** NULL끼리를 "같다"고 세면 한쪽이
                # 대부분 비어 있을 때 일치율이 부풀어 무관한 컬럼이 사본으로 보인다 —
                # 실측: `formula_1`의 races.time(경기 시각) vs results.time(완주 기록)이
                # 36.1% 불일치로 잡혔는데, 실제로 둘 다 값이 있는 행만 보면 전혀 다르다.
                # 조인 키와 비교 컬럼이 같은 이름일 수 있어(cdscode) 별칭으로 분리한다.
                x, y = "a.val::text", f"b.{_q(cb)}::text"
                d = f"{x} <> {y}"
                sql = (
                    f"WITH j AS (SELECT {_q(ka)} AS k, {_q(ca)} AS val "
                    f"           FROM {_q(schema)}.{_q(ta)} LIMIT {SAMPLE_LIMIT}) "
                    f"SELECT count(*) AS n, "
                    f"count(*) FILTER (WHERE {d}) AS diff, "
                    f"count(*) FILTER (WHERE {d} AND lower({x})=lower({y})) AS case_only, "
                    f"count(*) FILTER (WHERE {d} AND btrim({x})=btrim({y})) AS space_only, "
                    f"count(*) FILTER (WHERE {d} AND ({y} LIKE {x} || '%' "
                    f"                             OR {x} LIKE {y} || '%')) AS prefix, "
                    f"count(*) FILTER (WHERE {d} AND length({x})=50 AND length({y})>50) "
                    f"  AS truncated_50 "
                    f"FROM j a JOIN {_q(schema)}.{_q(tb)} b ON a.k = b.{_q(kb)} "
                    f"WHERE a.val IS NOT NULL AND b.{_q(cb)} IS NOT NULL"
                )
                try:
                    row = await _scalar(conn, schema, sql)
                except Exception as exc:  # noqa: BLE001
                    report.skipped.append(f"{ta}.{ca} vs {tb}.{cb}: {type(exc).__name__}")
                    continue
                if not row or (row["n"] or 0) < MIN_COMPARABLE_ROWS:
                    continue  # 비교 가능한 행이 너무 적으면 비율이 의미 없다
                pct = row["diff"] / row["n"] * 100
                divergences.append((f"{ta}.{ca}", f"{tb}.{cb}", row["n"], row["diff"], pct))
                if row["diff"]:
                    # 원인 분류는 부가 정보다 — 커넥터가 이 컬럼들을 안 돌려줘도
                    # 불일치 판정 자체는 성립해야 한다.
                    causes[f"{ta}.{ca} ↔ {tb}.{cb}"] = DivergenceCause(
                        total=row["n"], diff=row["diff"],
                        case_only=row.get("case_only", 0) or 0,
                        space_only=row.get("space_only", 0) or 0,
                        prefix=row.get("prefix", 0) or 0,
                        truncated_50=row.get("truncated_50", 0) or 0,
                    )

        # 완전히 갈리는 쌍은 "같은 이름의 다른 개념"이므로 중복 판정에서 뺀다.
        divergences = [d for d in divergences if d[4] <= MAX_DIVERGENCE_PCT]
        if not divergences:
            continue
        worst = max((d[4] for d in divergences), default=0.0)
        canonical = next(
            (f"{t}.{c}" for t, c in cand.columns if t in referenced), None
        )
        report.duplicate_concepts.append(DuplicateConcept(
            concept=cand.concept, columns=cand.columns,
            divergences=divergences, canonical=canonical, causes=causes,
        ))
        if worst <= 0:
            continue  # 사본이 완전히 일치한다 — 정합성 정상, 보고할 것 없음

        # **0% 초과는 전부 정합성 결함이다.** "같아야 할 값이 다르다"는 사실 자체가
        # 문제이고, 비율은 심각도일 뿐 성격이 아니다. 예전에는 2% 미만을 무해로
        # 걸렀는데, `schools.charternum`(0.09%, 1행)의 그 1행도 의미 차이가 아니라
        # 명백한 데이터 오류다.
        worst_pair = max(divergences, key=lambda d: d[4])
        key = f"{worst_pair[0]} ↔ {worst_pair[1]}"
        cause = causes.get(key)
        where = ", ".join(f"{t}.{c}" for t, c in cand.columns)
        severity = "high" if worst >= HIGH_DIVERGENCE_PCT else "medium"

        hints = []
        if cause:
            if cause.truncated_50:
                hints.append(f"{cause.truncated_50}건은 정확히 50자에서 잘렸습니다(적재 시 길이 제한)")
            elif cause.prefix:
                hints.append(f"{cause.prefix}건은 한쪽이 다른 쪽의 접두사입니다(절단 의심)")
            if cause.case_only:
                hints.append(f"{cause.case_only}건은 대소문자만 다릅니다")
            if cause.space_only:
                hints.append(f"{cause.space_only}건은 앞뒤 공백만 다릅니다")
        cause_text = (" 원인 추정: " + ", ".join(hints) + ".") if hints else ""

        impact = ("이 개념을 묻는 질문은 **어느 컬럼을 쓰느냐로 답이 갈립니다.** "
                  if severity == "high" else
                  "차이가 작아 대부분의 질문에서는 결과가 같지만, ")
        report.findings.append(Finding(
            kind="duplicate_concept", normal_form="3NF", severity=severity,
            title=f"'{cand.concept}' 사본이 어긋납니다 — {worst_pair[3]}/{worst_pair[2]}행 "
                  f"({worst:.2f}%) 불일치",
            detail=f"{where}. 같은 키를 조인했을 때 {key}가 "
                   f"{worst_pair[2]}행 중 {worst_pair[3]}행에서 다릅니다.{cause_text} "
                   f"같아야 할 값이 어긋난 것이므로 의미 차이가 아니라 **정합성 결함**입니다.",
            action=(f"{impact}"
                    f"근본 해결은 데이터를 맞추거나, 3NF로 "
                    f"{canonical or cand.columns[0][0]} 하나만 두고 나머지는 조인으로 "
                    f"참조하는 것입니다. 그 전까지는 정본을 "
                    f"{canonical or '한 컬럼'}으로 고정하세요."
                    + (" (FK가 참조하는 부모 테이블입니다.)" if canonical else "")),
            tables=sorted({t for t, _ in cand.columns}),
            columns=[f"{t}.{c}" for t, c in cand.columns],
        ))
