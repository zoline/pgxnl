"""Design Lab이 찾아낸 3NF 위반을 **실행 가능한 DDL 제안**으로 만든다.

Design Lab의 기존 `Finding.action`은 일부러 "지금 당장 할 수 있는 NL2SQL 대응"
(용어집 등록 등)으로 좁혀 뒀다(analyzer.py 참고) — 스키마 마이그레이션은 범위
밖이었다. 이 모듈은 그 범위 밖의 일, 실제로 스키마를 3NF로 바꾸려면 어떤 DDL이
필요한지를 만든다.

**보기 전용이다.** 여기서 만든 SQL을 자동으로 실행하지 않는다 — 스키마 변경은
사람이 검토하고 직접 실행할 일이다(design 문서 §5.9 검증 계층은 SELECT만
통과시키도록 만들어져 있고, 그 경계를 여기서 허물지 않는다).

## 4종 중 2종만 기계적으로 제안한다

```
transitive_dependency (코드 -> 이름)   깨끗하게 됨 — 룩업 테이블 CREATE
duplicate_concept (사본)              깨끗하게 됨 — 정본은 이미 찾아뒀다(canonical),
                                      FK 로 조인 경로도 안다
repeating_group (반복 컬럼)            제안 안 함 — "몇 번째 반복까지 의미있는
                                      데이터인지"는 사람 판단이 필요하다
mixed_grain (혼합 단위)                제안 안 함 — 3NF가 아니라 슈퍼타입/서브타입
                                      설계 문제라 기계적으로 가를 수 없다
```

## 근거 없는 제안은 만들지 않는다

`duplicate_concept`는 `canonical`(FK가 가리키는 정본 컬럼)이 없으면 건너뛴다 —
어느 쪽이 정본인지 모르는데 어느 쪽을 지우라고 할 수 없다. 조인 키도 실제
FK 메타에서만 가져오고, 없으면 그 컬럼은 건너뛴다(추측한 조인 조건을 DDL에
넣지 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pgxnl.agent.designlab.analyzer import SchemaReport, _q


@dataclass(frozen=True)
class SchemaProposal:
    """제안 하나. 어떤 finding에 대응하는지 `finding_title`로 짝짓는다(화면에서
    그 finding 바로 아래 붙여 보여주기 위함)."""

    finding_title: str
    kind: str          # "transitive_dependency" | "duplicate_concept"
    summary: str
    ddl: str
    caveats: list[str] = field(default_factory=list)
    #: 화면(단계별 적용 마법사)이 DDL 텍스트를 다시 파싱하지 않고 바로 쓸 수 있게
    #: 구조화된 값을 함께 담는다. kind별로 키가 다르다:
    #: transitive_dependency — table, code_column, name_column, code_type, name_type, lookup_table
    #: duplicate_concept     — table, column, canonical_table, canonical_column, local_key, ref_key, pct
    detail: dict[str, Any] = field(default_factory=dict)


def _slug(name: str) -> str:
    """제약조건·테이블 이름에 쓸 안전한 조각. 컬럼명에 공백·대문자가 흔해서
    (`"County Code"`) 그대로 이어붙이면 `fk_frpm_County Code`처럼 따옴표 없는
    식별자 안에 공백이 들어가 문법 오류가 난다(실측). 영숫자만 남기고 나머지는
    밑줄로 접는다."""
    import re as _re
    return _re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()


def _col_type(metas: dict[str, Any], table: str, column: str) -> str:
    m = metas.get(table)
    if m:
        for c in m.columns:
            if c.name == column:
                return c.data_type
    return "text"  # 못 찾으면 안전한 기본값 — 사람이 검토할 때 눈에 띈다


async def propose_3nf(report: SchemaReport, conn: Any) -> list[SchemaProposal]:
    """리포트에 담긴 이행 종속·중복 개념 findings 에서 DDL 제안을 만든다.

    Design Lab 전체와 같은 방침대로 매번 다시 조회한다(캐시 없음) — 필요한
    테이블만(대상 findings 가 언급한 것) `describe_table` 로 다시 읽는다.
    """
    schema = report.schema
    tables_needed = {td.table for td in report.transitive_dependencies}
    tables_needed |= {t for dc in report.duplicate_concepts for t, _ in dc.columns}

    metas: dict[str, Any] = {}
    for t in tables_needed:
        try:
            metas[t] = await conn.describe_table(schema, t)
        except Exception:  # noqa: BLE001 — 타입을 못 읽으면 text로 대체하고 계속한다
            continue

    out: list[SchemaProposal] = []
    out.extend(_propose_transitive(report, metas))
    out.extend(_propose_duplicates(report, metas))
    return out


def _propose_transitive(report: SchemaReport, metas: dict[str, Any]) -> list[SchemaProposal]:
    schema = report.schema
    # 같은 (테이블, 코드 컬럼)을 공유하는 이행 종속을 하나로 묶는다. 안 그러면
    # 코드 하나가 이름을 여러 개 결정할 때(실측: frpm.District Code가 District
    # Type과 District Name 둘 다 결정) 룩업 테이블 이름이 겹쳐서
    # `frpm_district_code_lookup`을 두 번 CREATE 하려는 DDL이 나온다 — 실제로
    # 실행하면 두 번째가 "테이블이 이미 있다"로 실패한다. 게다가 둘 다 같은
    # 코드가 정하는 속성이니 애초에 한 룩업 테이블에 같이 두는 게 맞는 3NF다.
    groups: dict[tuple[str, str], list[Any]] = {}
    for td in report.transitive_dependencies:
        groups.setdefault((td.table, td.code_column), []).append(td)

    out = []
    for (table, code), tds in groups.items():
        names = [td.name_column for td in tds]
        code_t = _col_type(metas, table, code)
        name_ts = [_col_type(metas, table, n) for n in names]
        # 새로 만드는 이름(테이블·제약조건·뷰)은 slug 를 쓴다 — 실제 컬럼 참조
        # (_q(code) 등)는 원래 이름을 그대로 따옴표로 감싸 쓴다. 둘을 섞으면
        # `fk_frpm_County Code`처럼 따옴표 없는 식별자에 공백이 들어가 문법
        # 오류가 난다(실측으로 확인).
        table_s, code_s = _slug(table), _slug(code)
        lookup = f"{table_s}_{code_s}_lookup"
        fk_name = f"fk_{table_s}_{code_s}"
        view_name = f"{table_s}_v"
        name_col_defs = ",\n  ".join(f"{_q(n)} {t} NOT NULL" for n, t in zip(names, name_ts))
        name_col_list = ", ".join(_q(n) for n in names)
        drop_lines = "\n".join(f"-- ALTER TABLE {schema}.{_q(table)} DROP COLUMN {_q(n)};" for n in names)
        view_select = ", ".join(f"lk.{_q(n)}" for n in names)
        codes_desc = ", ".join(f"{td.name_column}(코드 {td.distinct_codes}종)" for td in tds)
        ddl = f"""-- 3NF: {table}.{code} -> {codes_desc} 이행 종속 제거 (데이터로 확인됨)
CREATE TABLE {schema}.{_q(lookup)} (
  {_q(code)} {code_t} PRIMARY KEY,
  {name_col_defs}
);

INSERT INTO {schema}.{_q(lookup)} ({_q(code)}, {name_col_list})
SELECT DISTINCT {_q(code)}, {name_col_list}
FROM {schema}.{_q(table)}
WHERE {_q(code)} IS NOT NULL;

ALTER TABLE {schema}.{_q(table)}
  ADD CONSTRAINT {_q(fk_name)} FOREIGN KEY ({_q(code)}) REFERENCES {schema}.{_q(lookup)}({_q(code)});

-- {', '.join(names)} 컬럼은 이제 {lookup} 조인으로 얻는다. 기존 질의 호환이 필요하면 뷰를 두고,
-- 그 뒤에 원본 컬럼을 지운다(순서를 바꾸면 그 사이 질의가 깨진다):
-- CREATE VIEW {schema}.{_q(view_name)} AS
--   SELECT t.*, {view_select} FROM {schema}.{_q(table)} t
--   JOIN {schema}.{_q(lookup)} lk ON t.{_q(code)} = lk.{_q(code)};
{drop_lines}"""
        out.append(SchemaProposal(
            finding_title=f"{table}: {code} -> {', '.join(names)} 이행 종속",
            kind="transitive_dependency",
            summary=f"{lookup} 룩업 테이블로 분리 ({', '.join(names)})",
            ddl=ddl,
            caveats=[
                f'{", ".join(names)} 컬럼을 실제로 지우기 전에 그 컬럼을 참조하는 기존 SQL·애플리케이션이 있는지 확인하세요.',
                "DROP COLUMN은 예시에서 주석 처리해 뒀습니다 — 되돌릴 수 없는 작업입니다.",
            ],
            detail={
                "table": table, "code_column": code, "name_columns": names,
                "code_type": code_t, "name_types": name_ts, "lookup_table": lookup,
            },
        ))
    return out


def _propose_duplicates(report: SchemaReport, metas: dict[str, Any]) -> list[SchemaProposal]:
    schema = report.schema
    out = []
    for dc in report.duplicate_concepts:
        if not dc.canonical:
            continue  # 정본을 모르면(FK 방향 불명) 어느 쪽을 지우라고 할 수 없다
        canon_table, canon_col = dc.canonical.split(".", 1)
        for t, c in dc.columns:
            if f"{t}.{c}" == dc.canonical:
                continue  # 정본 자신은 지울 대상이 아니다

            key = None
            m = metas.get(t)
            if m:
                for local, ref_table, ref_col in m.foreign_keys:
                    if ref_table == canon_table:
                        key = (local, ref_col)
                        break
            if key is None:
                continue  # 조인 경로를 실제 FK로 확인 못 하면 추측해서 넣지 않는다
            local_key, ref_key = key

            worst = max(
                (d[4] for d in dc.divergences if d[0] == f"{t}.{c}" or d[1] == f"{t}.{c}"),
                default=0.0,
            )
            ddl = f"""-- 3NF: {t}.{c}는 {dc.canonical}의 사본입니다 ({worst:.2f}% 불일치 — 데이터로 확인됨)
-- 조회 시 조인으로 대체:
SELECT src.*, canon.{_q(canon_col)} AS {_q(c)}
FROM {schema}.{_q(t)} src
JOIN {schema}.{_q(canon_table)} canon ON src.{_q(local_key)} = canon.{_q(ref_key)};

-- 실제로 컬럼을 없애려면(되돌릴 수 없음, 불일치 원인부터 확인한 뒤에):
-- ALTER TABLE {schema}.{_q(t)} DROP COLUMN {_q(c)};"""
            out.append(SchemaProposal(
                finding_title=f"'{dc.concept}' 사본이 어긋납니다",
                kind="duplicate_concept",
                summary=f"{t}.{c} 제거, {dc.canonical}을 조인으로 참조",
                ddl=ddl,
                caveats=[
                    f"두 값이 {worst:.2f}% 불일치합니다 — 지우기 전에 어느 쪽이 맞는지(또는 둘 다 틀렸는지) 먼저 확인하세요.",
                    "DROP COLUMN은 예시에서 주석 처리해 뒀습니다.",
                ],
                detail={
                    "table": t, "column": c,
                    "canonical_table": canon_table, "canonical_column": canon_col,
                    "local_key": local_key, "ref_key": ref_key, "pct": round(worst, 2),
                },
            ))
    return out
