"""참조 컬럼이 그 테이블에 없는 경우 (`agent/missing_column.py`).

BIRD 459: `SELECT T1.street, T1.school FROM satscores AS T1 ...` — street·school은
schools에 있다. 검증 계층이 정확히 진단하지만 ReAct 루프가 끝난 뒤라 모델이 못 본다.
AliasFixRule도 못 고친다 — schools가 이 질의에 조인돼 있지 않아 조인을 새로 만들어야
하는데, 그것은 토큰 편집기의 범위를 넘는다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.missing_column import find_missing_columns
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

COLS = {
    "satscores": {"cds", "sname", "avgscrmath", "numtsttakr"},
    "schools": {"cdscode", "street", "school", "county"},
}
OWNERS = {
    "cds": {"satscores"}, "sname": {"satscores"}, "avgscrmath": {"satscores"},
    "numtsttakr": {"satscores"},
    "cdscode": {"schools"}, "street": {"schools"}, "school": {"schools"},
    "county": {"schools"},
}


@pytest.fixture
def parser():
    return AntlrPostgresParser()


def check(parser, sql):
    return find_missing_columns(parser.parse(sql), columns_by_table=COLS, owners=OWNERS)


def test_column_from_another_table_is_flagged(parser):
    out = check(parser, "SELECT T1.street, T1.school FROM satscores AS T1 "
                        "ORDER BY T1.avgscrmath DESC LIMIT 1 OFFSET 6")
    assert len(out) == 2
    assert out[0].alias == "t1" and out[0].table == "satscores"
    assert out[0].owners == ("schools",)
    assert "schools 테이블에 있습니다" in out[0].message()


def test_correct_reference_is_not_flagged(parser):
    assert check(parser, "SELECT T2.street FROM satscores AS T1 "
                         "JOIN schools AS T2 ON T1.cds = T2.cdscode") == []


def test_outer_reference_is_checked_even_with_a_subquery(parser):
    """서브쿼리가 있어도 **바깥 참조**는 판단할 수 있다. 예전엔 통째로 건너뛰어
    BIRD 447이 아무 가드에도 안 걸렸다(AliasFixRule도 서브쿼리면 포기한다)."""
    out = check(parser, "SELECT T1.street FROM satscores AS T1 "
                        "WHERE T1.cds IN (SELECT cdscode FROM schools)")
    assert len(out) == 1
    assert out[0].alias == "t1"


def test_inner_reference_is_not_checked(parser):
    """안쪽 참조는 안쪽 스코프를 따로 풀어야 판단할 수 있다 — 손대지 않는다."""
    assert check(parser, "SELECT T1.cds FROM satscores AS T1 "
                         "WHERE T1.cds IN (SELECT T2.street FROM schools AS T2)") == []


def test_already_joined_table_is_named_with_its_alias(parser):
    """조인하라는 말보다 별칭을 짚어주는 편이 실행하기 쉽다 (BIRD 447)."""
    out = check(parser, "SELECT T1.school FROM satscores AS T1 "
                        "JOIN schools AS T2 ON T1.cds = T2.cdscode "
                        "WHERE T1.cds > (SELECT max(T3.cds) FROM satscores AS T3)")
    assert len(out) == 1
    assert "t2" in out[0].message()
    assert "이미" in out[0].message()


def test_star_reference_is_skipped(parser):
    assert check(parser, "SELECT T1.* FROM satscores AS T1") == []


def test_unknown_table_is_skipped(parser):
    """컬럼 목록이 없는 테이블은 판단 근거가 없다."""
    assert check(parser, "SELECT T1.whatever FROM unknown_table AS T1") == []


def test_column_owned_by_nobody_says_so(parser):
    out = check(parser, "SELECT T1.nosuchcol FROM satscores AS T1")
    assert len(out) == 1
    assert out[0].owners == ()
    assert "어느 테이블에도 없습니다" in out[0].message()


# ---- 서브쿼리 안의 참조 (BIRD 447) ----

_CA = {
    "schools": {"cdscode", "school", "doc", "fundingtype", "street", "city", "county"},
    "frpm": {"cdscode", "enrollment (k-12)", "enrollment (ages 5-17)", "school name"},
    "satscores": {"cds", "sname", "avgscrmath", "numtsttakr"},
}
_OWNERS = {}
for _t, _cols in _CA.items():
    for _c in _cols:
        _OWNERS.setdefault(_c, set()).add(_t)


def _check(parser, sql):
    return find_missing_columns(parser.parse(sql), columns_by_table=_CA, owners=_OWNERS)


BIRD_447 = """
SELECT T1.school, T1.doc
FROM schools AS T1
INNER JOIN frpm AS T2 ON T1.cdscode = T2.cdscode
WHERE T1.fundingtype = 'Locally funded'
  AND (T2."Enrollment (K-12)" - T2."Enrollment (Ages 5-17)") > (
    SELECT AVG(T3."Enrollment (K-12)" - T3."Enrollment (Ages 5-17)")
    FROM schools AS T3
    INNER JOIN frpm AS T4 ON T3.cdscode = T4.cdscode
    WHERE T3.fundingtype = 'Locally funded'
  )
"""


def test_서브쿼리_안의_잘못된_별칭을_잡는다(parser) -> None:
    """초판은 안쪽 참조를 통째로 건너뛰어 447이 네 run 연속 실행 오류로 죽었다."""
    found = _check(parser, BIRD_447)
    assert len(found) == 2
    assert all(f.table == "schools" for f in found)
    # column은 표시용이라 원본 대소문자를 유지한다 (조회는 소문자로 한다)
    assert {f.column.lower() for f in found} == {"enrollment (k-12)", "enrollment (ages 5-17)"}


def test_메시지가_같은_스코프의_별칭을_짚어준다(parser) -> None:
    msg = _check(parser, BIRD_447)[0].message()
    assert "frpm" in msg and "t4" in msg   # 바깥의 t2가 아니라 안쪽의 t4
    assert "t2" not in msg


def test_바깥의_정상_참조는_오탐하지_않는다(parser) -> None:
    # T2 = frpm 이고 컬럼이 실제로 있다 — 스코프를 안 가르면 여기서 오탐이 난다.
    found = _check(parser, BIRD_447)
    assert not any(f.alias == "t2" for f in found)


def test_같은_별칭이_스코프마다_다른_테이블이어도_구분한다(parser) -> None:
    sql = """
    SELECT T1.school FROM schools AS T1
    WHERE T1.cdscode IN (SELECT T1.cdscode FROM frpm AS T1 WHERE T1."Enrollment (K-12)" > 0)
    """
    # 안쪽 T1 = frpm 이라 "Enrollment (K-12)"가 있다. 평면 dict면 한쪽을 오탐한다.
    assert _check(parser, sql) == []


def test_상관_서브쿼리가_바깥_별칭을_봐도_된다(parser) -> None:
    sql = """
    SELECT T1.school FROM schools AS T1
    WHERE T1.cdscode IN (SELECT T2.cdscode FROM frpm AS T2 WHERE T2.cdscode = T1.cdscode)
    """
    assert _check(parser, sql) == []


def test_상관_서브쿼리에서_바깥_테이블에_없는_컬럼은_잡는다(parser) -> None:
    sql = """
    SELECT T1.school FROM schools AS T1
    WHERE T1.cdscode IN (SELECT T2.cdscode FROM frpm AS T2 WHERE T2.cdscode = T1."Enrollment (K-12)")
    """
    found = _check(parser, sql)
    assert len(found) == 1 and found[0].table == "schools"
