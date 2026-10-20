"""데이터 검증 테스트 (`designlab.analyzer`).

핵심 원칙: **"위반"이 아니라 "답이 갈리는 것"만 보고한다.** 실측에서 `county`는
3개 테이블에 중복이지만 값 불일치가 0%였다 — 어느 사본을 써도 결과가 같으므로
경고하면 소음이다. 반대로 `school name`은 2.5%가 갈려서, BIRD 30문항 중 12개가
그 컬럼을 쓰는 상황에서 모델이 정답 논리를 알아도 틀리게 만든다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from pgxnl.agent.designlab import analyze_schema


@dataclass
class Col:
    name: str


@dataclass
class Tbl:
    schema: str
    name: str
    comment: str | None
    columns: list
    foreign_keys: list


class FakeConn:
    """카탈로그는 고정, 데이터 질의는 등록해 둔 답을 돌려준다."""

    def __init__(self, tables: dict[str, list[str]], fks: dict[str, list], answers: dict) -> None:
        self._tables = tables
        self._fks = fks
        self.answers = answers
        self.queries: list[str] = []

    async def list_tables(self, schema: str):
        return [Tbl(schema, t, None, [], []) for t in self._tables]

    async def describe_table(self, schema: str, table: str):
        return Tbl(schema, table, None, [Col(c) for c in self._tables[table]],
                   self._fks.get(table, []))

    async def execute_readonly(self, sql, *, row_limit, timeout_seconds, schema):
        self.queries.append(sql)
        for needle, answer in self.answers.items():
            if all(part in sql for part in needle):
                return [answer]
        return [{"n": 0, "diff": 0, "codes": 0, "violated": 0, "total": 0}]


CATALOG = {"schools": ["cdscode", "county", "school", "soc", "soctype"],
           "frpm": ["cdscode", "County Name", "School Name"]}
FKS = {"frpm": [("cdscode", "schools", "cdscode")]}


def conn(answers):
    return FakeConn(CATALOG, FKS, answers)


@pytest.mark.asyncio
async def test_diverging_concept_is_reported_as_high():
    c = conn({("School Name", "diff"): {"n": 9986, "diff": 252},
              ("County Name", "diff"): {"n": 9986, "diff": 0},
              ("cdscode", "diff"): {"n": 9986, "diff": 0}})
    r = await analyze_schema(c, target_name="T", schema="s")
    high = [f for f in r.findings if f.severity == "high"]
    assert len(high) == 1
    assert "school" in high[0].title
    assert "2.52%" in high[0].title
    assert "정합성 결함" in high[0].detail


@pytest.mark.asyncio
async def test_small_divergence_is_still_reported_as_an_integrity_defect():
    """**0% 초과는 전부 정합성 결함이다.** 같아야 할 값이 다르다는 사실 자체가 문제이고,
    비율은 심각도일 뿐 성격이 아니다 — `schools.charternum`(1,167행 중 1행)의 그 1행도
    의미 차이가 아니라 데이터 오류다."""
    c = conn({("School Name", "diff"): {"n": 1167, "diff": 1}})
    r = await analyze_schema(c, target_name="T", schema="s")
    found = [f for f in r.findings if f.kind == "duplicate_concept"]
    assert len(found) == 1 and found[0].severity == "medium"
    assert "정합성 결함" in found[0].detail


@pytest.mark.asyncio
async def test_cause_hints_are_included_when_available():
    """원인을 알아야 고칠 수 있다 — 실측에서 satscores.sname 불일치 102건 중 46건이
    정확히 50자에서 잘려 있었다(적재 시 길이 제한)."""
    c = conn({("School Name", "diff"): {
        "n": 1749, "diff": 102, "case_only": 1, "space_only": 0,
        "prefix": 53, "truncated_50": 46}})
    r = await analyze_schema(c, target_name="T", schema="s")
    f = next(f for f in r.findings if f.kind == "duplicate_concept")
    assert "50자에서 잘렸습니다" in f.detail
    assert "대소문자만" in f.detail


@pytest.mark.asyncio
async def test_identical_copies_are_not_reported():
    """값이 같으면 어느 사본을 써도 결과가 같다 — 경고하면 소음이다."""
    c = conn({("diff",): {"n": 9986, "diff": 0}})
    r = await analyze_schema(c, target_name="T", schema="s")
    assert [f for f in r.findings if f.kind == "duplicate_concept"] == []
    # 다만 분석 결과 자체에는 남아 있어야 한다(0%임을 확인했다는 사실이 정보다)
    assert {d.concept for d in r.duplicate_concepts} >= {"school", "county"}


@pytest.mark.asyncio
async def test_canonical_is_the_fk_parent_table():
    """FK가 참조하는 쪽이 정본 후보다 — BIRD gold도 79%가 부모 테이블을 쓴다."""
    c = conn({("School Name", "diff"): {"n": 100, "diff": 10}})
    r = await analyze_schema(c, target_name="T", schema="s")
    school = next(d for d in r.duplicate_concepts if d.concept == "school")
    assert school.canonical == "schools.school"


@pytest.mark.asyncio
async def test_transitive_dependency_is_reported():
    c = conn({("soctype", "violated"): {"codes": 21, "violated": 0, "total": 17686}})
    r = await analyze_schema(c, target_name="T", schema="s")
    assert any(t.code_column == "soc" and t.name_column == "soctype"
               for t in r.transitive_dependencies)


@pytest.mark.asyncio
async def test_keylike_code_is_not_a_transitive_dependency():
    """코드가 사실상 키면 모든 컬럼을 자명하게 결정한다 — 보고할 게 없다.
    실측에서 frpm."School Code"(9,942종/9,986행)가 소음으로 잡혔다."""
    c = conn({("soctype", "violated"): {"codes": 9942, "violated": 0, "total": 9986}})
    r = await analyze_schema(c, target_name="T", schema="s")
    assert r.transitive_dependencies == []


@pytest.mark.asyncio
async def test_broken_functional_dependency_is_not_reported():
    """같은 코드가 여러 이름을 가지면 함수 종속이 아니다."""
    c = conn({("soctype", "violated"): {"codes": 21, "violated": 3, "total": 17686}})
    r = await analyze_schema(c, target_name="T", schema="s")
    assert r.transitive_dependencies == []


@pytest.mark.asyncio
async def test_query_failure_is_recorded_not_raised():
    class Boom(FakeConn):
        async def execute_readonly(self, *a, **kw):
            raise TimeoutError

    r = await analyze_schema(Boom(CATALOG, FKS, {}), target_name="T", schema="s")
    assert r.skipped  # 무엇을 못 봤는지 남아야 리포트를 신뢰할 수 있다


@pytest.mark.asyncio
async def test_join_key_and_compared_column_may_share_a_name():
    """cdscode끼리 비교하면 SELECT에서 이름이 충돌한다 — 별칭으로 분리해야 한다."""
    c = conn({("cdscode", "diff"): {"n": 9986, "diff": 0}})
    await analyze_schema(c, target_name="T", schema="s")
    joins = [q for q in c.queries if " JOIN " in q]
    assert joins and all("AS val" in q for q in joins)


# ── 혼합 단위 / 선택적 컬럼 ────────────────────────────────────────────────
# 실측(BIRD `satscores`): `rtype='S'`는 학교 1,749행, `rtype='D'`는 교육구 520행이고
# 'D' 행은 `sname`이 전부 NULL이다. `numtsttakr` 합계가 209,913 vs 419,987로 정확히
# 2배 — 교육구 행이 소속 학교를 이미 집계하고 있다.

SAT = {"satscores": ["cds", "rtype", "sname", "numtsttakr"]}


def grain_conn(distinct: dict, groups: list[dict]):
    class C(FakeConn):
        async def execute_readonly(self, sql, *, row_limit, timeout_seconds, schema):
            self.queries.append(sql)
            if "count(DISTINCT" in sql:
                return [distinct]
            if "GROUP BY 1" in sql and "_v" in sql:
                return groups
            return [{"n": 0, "diff": 0, "codes": 0, "violated": 0, "total": 0}]

    return C(SAT, {}, {})


@pytest.mark.asyncio
async def test_missing_identity_column_is_high_severity():
    """이름이 없는 행은 다른 종류의 개체다 — 집계 시 중복 계산 위험이 있다."""
    c = grain_conn({"cds": 2269, "rtype": 2, "sname": 1665, "numtsttakr": 300},
                   [{"_v": "S", "_n": 1749, "cds": 1749, "sname": 1749, "numtsttakr": 1749},
                    {"_v": "D", "_n": 520, "cds": 520, "sname": 0, "numtsttakr": 520}])
    r = await analyze_schema(c, target_name="T", schema="s")
    grain = [f for f in r.findings if f.kind == "mixed_grain"]
    assert len(grain) == 1 and grain[0].severity == "high"
    assert "sname" in grain[0].detail
    assert "자동으로 필터를 넣지 마세요" in grain[0].action


@pytest.mark.asyncio
async def test_optional_attribute_is_only_info():
    """이름은 있는데 부가 속성만 비면 '부류에 따른 선택적 속성'이다."""
    c = grain_conn({"cds": 2269, "rtype": 2, "sname": 1665, "numtsttakr": 300},
                   [{"_v": "S", "_n": 1749, "cds": 1749, "sname": 1749, "numtsttakr": 1749},
                    {"_v": "D", "_n": 520, "cds": 520, "sname": 520, "numtsttakr": 0}])
    r = await analyze_schema(c, target_name="T", schema="s")
    grain = [f for f in r.findings if f.kind == "mixed_grain"]
    assert len(grain) == 1 and grain[0].severity == "info"


@pytest.mark.asyncio
async def test_tiny_partitions_are_ignored():
    """4행짜리 파티션에서 어떤 컬럼이 전부 NULL인 것은 통계적으로 의미가 없다 —
    초기 구현에서 frpm."District Type"='Non-School Locations'(4행)가 무더기로 잡혔다."""
    c = grain_conn({"cds": 2269, "rtype": 2, "sname": 1665, "numtsttakr": 300},
                   [{"_v": "S", "_n": 2265, "cds": 2265, "sname": 2265, "numtsttakr": 2265},
                    {"_v": "X", "_n": 4, "cds": 4, "sname": 0, "numtsttakr": 4}])
    r = await analyze_schema(c, target_name="T", schema="s")
    assert [f for f in r.findings if f.kind == "mixed_grain"] == []


@pytest.mark.asyncio
async def test_uniformly_populated_column_is_not_flagged():
    c = grain_conn({"cds": 2269, "rtype": 2, "sname": 1665, "numtsttakr": 300},
                   [{"_v": "S", "_n": 1749, "cds": 1749, "sname": 1749, "numtsttakr": 1749},
                    {"_v": "D", "_n": 520, "cds": 520, "sname": 520, "numtsttakr": 520}])
    r = await analyze_schema(c, target_name="T", schema="s")
    assert r.mixed_grains == []


@pytest.mark.asyncio
async def test_correlated_discriminators_report_once():
    """eilcode/eilname처럼 1:1인 두 컬럼은 같은 분할을 만든다 — 한 번만 보고한다."""
    tables = {"t": ["code", "name", "attr"]}
    groups = [{"_v": "A", "_n": 700, "code": 700, "name": 700, "attr": 700},
              {"_v": "B", "_n": 300, "code": 300, "name": 300, "attr": 0}]

    class C(FakeConn):
        async def execute_readonly(self, sql, *, row_limit, timeout_seconds, schema):
            if "count(DISTINCT" in sql:
                return [{"code": 2, "name": 2, "attr": 5}]
            if "_v" in sql:
                return groups
            return [{"n": 0, "diff": 0, "codes": 0, "violated": 0, "total": 0}]

    r = await analyze_schema(C(tables, {}, {}), target_name="T", schema="s")
    assert len(r.mixed_grains) == 1


@pytest.mark.asyncio
async def test_completely_diverging_pair_is_not_a_duplicate():
    """100% 불일치는 '위험한 중복'이 아니라 '애초에 중복이 아니다'라는 뜻이다 —
    진짜 사본은 대부분 일치하면서 일부만 어긋난다(학교명 2.1%)."""
    c = conn({("School Name", "diff"): {"n": 9986, "diff": 9986}})
    r = await analyze_schema(c, target_name="T", schema="s")
    assert [f for f in r.findings if f.kind == "duplicate_concept"] == []


@pytest.mark.asyncio
async def test_too_few_comparable_rows_is_ignored():
    """양쪽 다 값이 있는 행이 적으면 비율이 의미 없다."""
    c = conn({("School Name", "diff"): {"n": 10, "diff": 3}})
    r = await analyze_schema(c, target_name="T", schema="s")
    assert [f for f in r.findings if f.kind == "duplicate_concept"] == []


@pytest.mark.asyncio
async def test_comparison_counts_only_rows_where_both_are_present():
    """NULL끼리를 '같다'고 세면 한쪽이 대부분 비었을 때 일치율이 부풀어 무관한 컬럼이
    사본으로 보인다(실측: formula_1의 races.time vs results.time)."""
    c = conn({("School Name", "diff"): {"n": 9986, "diff": 252}})
    await analyze_schema(c, target_name="T", schema="s")
    joins = [q for q in c.queries if " JOIN " in q]
    assert joins and all("IS NOT NULL" in q for q in joins)
