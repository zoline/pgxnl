"""Design Lab이 찾아낸 구조에서 **용어집 항목을 데이터로 유도한다**.

동기: 손으로 등록한 용어집 15건을 뜯어보니 정보를 담고 있는 것(코드 매핑, 값 나열)은
전부 DB 안에 이미 있었다 — 사람이 CDE 문서를 찾아 옮겨 적은 내용이
`SELECT DISTINCT soc, soctype`의 결과와 같다. 옮겨 적는 과정에서 오타(`shcools`)와
규칙 문장("~하세요")이 섞여 들어가기도 했다.

**유도할 수 없는 것은 만들지 않는다.** `avgscrwrite`가 "이미 계산된 학교별 평균"이라는
사실이나 `gsserved`와 `gsoffered`의 차이는 데이터에 없다 — 그런 항목은 사람이 쓴다.
자동 생성이 사람의 지식을 대체하는 게 아니라, **기계가 알 수 있는 부분을 사람 손에서
덜어내는** 것이 목적이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pgxnl.agent.designlab.analyzer import SchemaReport, _q

#: 값을 나열할 최대 개수. 넘으면 용어집이 프롬프트를 압도한다 — 실측에서 용어집이
#: 테이블 블록을 두 배로 키워 모델의 테이블 선택을 왜곡했다(2026-09-04).
MAX_VALUES = 20

#: 값 나열 후보로 볼 고유값 개수의 상한. 이보다 많으면 "분류 코드"가 아니라 데이터다.
MAX_ENUM_CARDINALITY = 20

#: 코드 매핑은 값 나열보다 정보량이 많아 조금 더 허용한다 — `schools.soc`가 21종이라
#: 20에 걸려 빠졌는데, BIRD 질문이 실제로 가장 많이 쓰는 코드다.
MAX_CODE_MAP_CARDINALITY = 30

#: 값 하나의 길이 상한. 긴 자유 텍스트는 분류값이 아니다.
MAX_VALUE_LENGTH = 60

#: 사본이 이 비율 미만으로 갈리면 정본을 적을 이유가 없다 — 어느 쪽을 써도 같다.
MIN_CANONICAL_DIVERGENCE_PCT = 2.0


@dataclass(frozen=True)
class GlossarySuggestion:
    """등록 가능한 형태로 만든 제안. 그대로 `pgxnl_glossary`에 넣을 수 있다."""

    kind: str            # "code_map" | "value_enum" | "canonical"
    schema_name: str
    table_name: str
    column_name: str
    term: str
    definition: str
    source: str          # 어떤 질의로 유도했는지 — 사람이 나중에 검증할 수 있어야 한다
    rationale: str       # 왜 이 항목이 필요한지 (화면 표시용)


def _fmt_values(values: list[Any]) -> str:
    out: list[str] = []
    for v in values:
        text = str(v).strip()
        if text and len(text) <= MAX_VALUE_LENGTH:
            out.append(text)
        if len(out) >= MAX_VALUES:
            break
    return ", ".join(out)


async def suggest_glossary(
    conn: Any, *, schema: str, report: SchemaReport
) -> list[GlossarySuggestion]:
    """리포트에 담긴 구조를 근거로 용어집 항목을 만든다. 읽기 전용 SQL만 쓴다."""
    out: list[GlossarySuggestion] = []
    code_maps = await _from_code_maps(conn, schema, report)
    out += code_maps
    # 코드 매핑이 이미 `코드=이름`을 다 싣고 있으므로 이름 쪽 컬럼을 따로 나열하면
    # 같은 값 목록이 두 번 실린다(soc/soctype, doc/doctype, eilcode/eilname).
    covered = {
        (dep.table, dep.name_column.lower())
        for dep in report.transitive_dependencies
        if any(s.table_name == dep.table and s.column_name == dep.code_column
               for s in code_maps)
    }
    out += [s for s in await _from_value_enums(conn, schema, report)
            if (s.table_name, s.column_name.lower()) not in covered]
    # 같은 컬럼에 여러 제안이 생기면 앞선 것(코드 매핑)을 남긴다 — 정보량이 더 많다.
    seen: set[tuple[str, str]] = set()
    unique: list[GlossarySuggestion] = []
    for s in out:
        key = (s.table_name, s.column_name.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return unique


async def _from_code_maps(
    conn: Any, schema: str, report: SchemaReport
) -> list[GlossarySuggestion]:
    """이행 종속 `코드 -> 이름`을 `Values: 코드=이름, ...`으로 옮긴다.

    손으로 등록한 DOC/SOC 항목이 정확히 이 형태였다.
    """
    out: list[GlossarySuggestion] = []
    for dep in report.transitive_dependencies:
        if dep.distinct_codes > MAX_CODE_MAP_CARDINALITY:
            continue  # 코드가 너무 많으면 분류가 아니라 데이터다
        sql = (
            f"SELECT DISTINCT {_q(dep.code_column)} AS code, {_q(dep.name_column)} AS label "
            f"FROM {_q(schema)}.{_q(dep.table)} "
            f"WHERE {_q(dep.code_column)} IS NOT NULL AND {_q(dep.name_column)} IS NOT NULL "
            f"ORDER BY 1"
        )
        try:
            rows = await conn.execute_readonly(
                sql, row_limit=MAX_VALUES + 1, timeout_seconds=60, schema=schema
            )
        except Exception:  # noqa: BLE001 — 유도 실패는 제안을 안 하면 그만이다
            continue
        pairs = _fmt_values([f"{dict(r)['code']}={dict(r)['label']}" for r in rows])
        if not pairs:
            continue
        out.append(GlossarySuggestion(
            kind="code_map", schema_name=schema, table_name=dep.table,
            column_name=dep.code_column,
            term=f"{dep.code_column}, {dep.name_column}",
            definition=f"Values: {pairs}",
            source=sql,
            rationale=(f"{dep.table}.{dep.code_column} 값이 {dep.name_column}을(를) "
                       f"결정합니다(이행 종속). 질문이 이름으로 물어도 코드로 필터할 수 "
                       f"있게 매핑을 싣습니다."),
        ))
    return out


async def _from_value_enums(
    conn: Any, schema: str, report: SchemaReport
) -> list[GlossarySuggestion]:
    """고유값이 적은 컬럼의 값을 그대로 나열한다.

    손으로 등록한 `Virtual: F/V/C/N`, `StatusType: Active/Closed/...`가 이 형태다.
    **질문이 값을 그대로 인용하는 경우가 많아**(예: "Locally funded" 학교) 모델이
    정확한 문자열을 알아야 필터를 만들 수 있다.

    고유값 개수는 `analyzer`가 혼합 단위를 찾으면서 이미 세어 뒀다 — 재질의하지 않는다.
    """
    out: list[GlossarySuggestion] = []
    for (table, col), n in sorted(report.distinct_counts.items()):
        if not 2 <= n <= MAX_ENUM_CARDINALITY:
            continue
        sql = (f"SELECT DISTINCT {_q(col)} AS v FROM {_q(schema)}.{_q(table)} "
               f"WHERE {_q(col)} IS NOT NULL ORDER BY 1")
        try:
            rows = await conn.execute_readonly(
                sql, row_limit=MAX_VALUES + 1, timeout_seconds=60, schema=schema
            )
        except Exception:  # noqa: BLE001
            continue
        values = _fmt_values([dict(r)["v"] for r in rows])
        if not values:
            continue
        out.append(GlossarySuggestion(
            kind="value_enum", schema_name=schema, table_name=table, column_name=col,
            term=col,
            definition=f"Values: {values}",
            source=sql,
            rationale=("고유값이 적은 분류 컬럼입니다. 질문이 값을 그대로 인용할 때 "
                       "모델이 정확한 문자열을 쓰도록 나열합니다."),
        ))
    return out


def canonical_marks(report: SchemaReport) -> dict[str, dict[str, str]]:
    """`{테이블: {컬럼: 표시문구}}` — mschema 컬럼 줄에 넣을 정본 표시.

    값이 갈리는 사본에만 붙인다. 불일치가 0%면 어느 쪽을 써도 결과가 같으므로 알려줄
    이유가 없다 — `california_schools`의 county/district가 그렇다(3개 테이블 중복이지만
    0%). 실제로 붙는 것은 `frpm."School Name"` 하나뿐이다.

    표시 대상이 아니라 **정본 자신**에는 붙이지 않는다. 사본 쪽에만 "이건 저기 것의
    사본"이라고 적어야 어느 쪽으로 가야 하는지가 드러난다.
    """
    marks: dict[str, dict[str, str]] = {}
    for dup in report.duplicate_concepts:
        if not dup.canonical or not dup.divergences:
            continue
        worst = max(d[4] for d in dup.divergences)
        if worst < MIN_CANONICAL_DIVERGENCE_PCT:
            continue
        for table, column in dup.columns:
            if f"{table}.{column}" == dup.canonical:
                continue
            marks.setdefault(table, {})[column] = (
                f"copy of {dup.canonical} — differs in {worst:.1f}% of rows"
            )
    return marks
