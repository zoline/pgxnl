"""사본 컬럼을 정본으로 교정 (`CanonicalColumnRule`).

배경: Design Lab이 `frpm."School Name"`과 `schools.school`이 같은 학교 이름인데
9,941행 중 207행(2.1%)이 다르다는 것을 찾아냈다 — **어느 쪽을 쓰느냐로 답이 갈린다.**

같은 내용을 프롬프트 규칙으로 세 번 시도해 세 번 실패했다(id=26 두 번, id=27 한 번).
스키마에 `copy of schools.school` 표시를 넣고 "표시된 컬럼 대신 X를 쓰라"고 명시해도
목표 문항 seq 442가 6회 모두 안 움직였다. 그래서 결정론적 교정으로 옮겼다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import CanonicalColumnRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

COPIES = {("frpm", "school name"): ("schools", "school"),
          ("satscores", "sname"): ("schools", "school")}


@pytest.fixture
def parser():
    return AntlrPostgresParser()


def run(parser, sql, copies=None):
    rule = CanonicalColumnRule(COPIES if copies is None else copies)
    return " ".join(canonicalize_sql(sql, parser, [rule]).split())


# 파서가 별칭을 소문자로 저장하므로 교정 결과도 소문자다(`T2` -> `t2`).
# PostgreSQL은 인용 없는 식별자를 소문자로 접으므로 동작은 같다 — AliasFixRule도 같다.


def test_copy_is_rewritten_when_canonical_table_is_joined(parser):
    """BIRD seq 442 — schools를 이미 조인했으므로 정본을 써야 한다."""
    out = run(parser, 'SELECT T1."School Name", T2.street FROM frpm AS T1 '
                      'INNER JOIN schools AS T2 ON T1.cdscode = T2.cdscode')
    assert "t2.school," in out
    assert '"School Name"' not in out


def test_untouched_when_canonical_table_is_absent(parser):
    """BIRD seq 443의 gold는 사본을 쓴다 — schools를 조인하지 않기 때문이다.
    정본을 쓰겠다고 조인을 새로 추가하면 안 된다."""
    sql = ('SELECT T2."School Name" FROM satscores AS T1 '
           'INNER JOIN frpm AS T2 ON T1.cds = T2.cdscode')
    assert run(parser, sql) == " ".join(sql.split())


def test_rewrites_every_reference_not_just_select(parser):
    out = run(parser, 'SELECT T1."School Name" FROM frpm AS T1 JOIN schools AS T2 '
                      'ON T1.cdscode = T2.cdscode WHERE T1."School Name" LIKE \'A%\' '
                      'ORDER BY T1."School Name"')
    assert out.count("t2.school") == 3
    assert '"School Name"' not in out


def test_canonical_reference_is_left_alone(parser):
    sql = 'SELECT T2.school FROM frpm AS T1 JOIN schools AS T2 ON T1.cdscode = T2.cdscode'
    assert run(parser, sql) == " ".join(sql.split())


def test_unrelated_columns_are_left_alone(parser):
    sql = 'SELECT T1.cdscode, T2.street FROM frpm AS T1 JOIN schools AS T2 ON T1.cdscode = T2.cdscode'
    assert run(parser, sql) == " ".join(sql.split())


def test_derived_table_alias_is_skipped(parser):
    """FROM 안의 서브쿼리에 붙은 별칭은 테이블 별칭이 아니다 — 그 컬럼은 서브쿼리가
    이미 골라 놓은 것이라 정본 테이블 컬럼으로 바꿔치면 다른 값을 읽는다. 파서는 파생
    별칭을 마지막으로 본 테이블에 묶으므로(`x: frpm`) 별칭 충돌로는 안 걸린다."""
    sql = ('SELECT x."School Name" FROM (SELECT "School Name" FROM frpm) x '
           'JOIN schools AS T2 ON true')
    assert run(parser, sql) == " ".join(sql.split())


def test_scalar_subquery_does_not_block_the_rewrite(parser):
    """예전엔 서브쿼리가 하나라도 있으면 전부 포기했다. 실제 위험은 별칭이 두 테이블에
    묶이는 것뿐이라, 별칭이 겹치지 않는 스칼라 서브쿼리는 교정해도 안전하다 —
    BIRD 447의 pred가 정확히 이 모양이었고(WHERE의 AVG 서브쿼리) 그 때문에 막혀 있었다."""
    out = run(parser, 'SELECT T1."School Name" FROM frpm AS T1 '
                      'JOIN schools AS T2 ON T1.cdscode = T2.cdscode '
                      'WHERE T1.x > (SELECT AVG(T3.y) FROM frpm AS T3)')
    assert "t2.school" in out
    assert '"School Name"' not in out


def test_alias_bound_to_two_tables_is_skipped(parser):
    """같은 별칭을 바깥과 서브쿼리가 서로 다른 테이블에 쓰면 평면 dict가 안쪽으로
    덮어써, 바깥 컬럼을 엉뚱한 테이블로 오해한다 — 조용한 오답이 되므로 손대지 않는다."""
    sql = ('SELECT a."School Name" FROM frpm AS a '
           'WHERE a.y > (SELECT max(a.z) FROM schools AS a)')
    assert run(parser, sql) == " ".join(sql.split())


def test_identifier_needing_quotes_is_quoted(parser):
    out = run(parser, 'SELECT T1.sname FROM satscores AS T1 JOIN schools AS T2 '
                      'ON T1.cds = T2.cdscode',
              {("satscores", "sname"): ("schools", "School Name")})
    assert 't2."School Name"' in out


def test_no_copies_means_no_edits(parser):
    sql = 'SELECT T1."School Name" FROM frpm AS T1 JOIN schools AS T2 ON T1.cdscode = T2.cdscode'
    assert run(parser, sql, {}) == " ".join(sql.split())


def test_table_name_used_as_its_own_alias(parser):
    out = run(parser, 'SELECT frpm."School Name" FROM frpm JOIN schools ON frpm.cdscode = schools.cdscode')
    assert "schools.school" in out


def test_inner_alias_is_not_used_for_outer_reference(parser):
    """서브쿼리 안에만 있는 별칭을 바깥 참조의 대체로 쓰면 실행이 죽는다.

    실측(BIRD 447, 2026-09-10): `T1."School Name"`을 `t4.school`로 고쳤는데 t4는 스칼라
    서브쿼리 안에만 있어 `missing FROM-clause entry for table "t4"`가 났다. 2026-09-09에
    "서브쿼리가 있으면 전부 포기"를 완화하면서 생긴 회귀다 — 별칭이 t1~t4로 전부 달라
    `ambiguous_aliases`로는 걸리지 않는다.
    """
    out = run(parser, 'SELECT T1."School Name", T2.doc FROM frpm AS T1 '
                      'INNER JOIN schools AS T2 ON T1.cdscode = T2.cdscode '
                      'WHERE (T1.a - T1.b) > (SELECT AVG(T3.a - T3.b) FROM frpm AS T3 '
                      'INNER JOIN schools AS T4 ON T3.cdscode = T4.cdscode)')
    assert "t2.school" in out
    assert "t4.school" not in out


def test_no_rewrite_when_canonical_table_is_only_inside_a_subquery(parser):
    """정본 테이블이 바깥에 없으면 손대지 않는다 — 조인을 새로 만들 수는 없다."""
    sql = ('SELECT T1."School Name" FROM frpm AS T1 '
           'WHERE T1.x > (SELECT 1 FROM schools AS T4)')
    assert run(parser, sql) == " ".join(sql.split())


def test_bare_table_name_inside_subquery_is_not_used_either(parser):
    """별칭 없이 쓴 테이블 이름도 그 자체가 참조 이름이 된다 — 안쪽 것은 못 쓴다."""
    sql = 'SELECT T1."School Name" FROM frpm AS T1 WHERE T1.x > (SELECT 1 FROM schools)'
    assert run(parser, sql) == " ".join(sql.split())


def test_bare_table_name_in_outer_from_is_usable(parser):
    out = run(parser, 'SELECT T1."School Name" FROM frpm AS T1 '
                      'JOIN schools ON T1.cdscode = schools.cdscode')
    assert "schools.school" in out
