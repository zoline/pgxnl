"""필터에 기여하지 않는 조인 감지 (`agent/redundant_join.py`).

BIRD 443 실측: 모델이 `schools`를 조인해 놓고 WHERE에서 쓰지 않고, 학교 이름을
`frpm."School Name"` 대신 `schools.school`에서 가져오려고만 붙였다. 두 컬럼은 같은
개념의 사본이고 9,941행 중 207행이 달라 어느 쪽을 쓰느냐로 답이 갈린다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.redundant_join import find_redundant_joins
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

COPIES = {("frpm", "school name"): ("schools", "school")}


@pytest.fixture
def parser():
    return AntlrPostgresParser()


def check(parser, sql, copies=None):
    stmt = parser.parse(sql)
    return find_redundant_joins(
        parser.to_ir(stmt),
        alias_to_table=dict(stmt.alias_to_table or {}),
        copies=COPIES if copies is None else copies,
    )


def test_join_used_only_in_select_is_flagged(parser):
    out = check(parser, 'SELECT T3.school FROM frpm AS T1 '
                        'INNER JOIN satscores AS T2 ON T1.cdscode = T2.cds '
                        'INNER JOIN schools AS T3 ON T1.cdscode = T3.cdscode '
                        'WHERE T2.numge1500 > 0')
    assert len(out) == 1
    assert out[0].alias == "t3"
    assert out[0].replacement_table == "frpm"
    assert "school name" in out[0].message()


def test_join_used_in_where_is_not_flagged(parser):
    """조건에 기여하면 그 조인은 필요한 것이다."""
    assert check(parser, 'SELECT T3.school FROM frpm AS T1 '
                         'INNER JOIN schools AS T3 ON T1.cdscode = T3.cdscode '
                         'WHERE T3.doc = 54') == []


def test_join_used_in_order_by_is_not_flagged(parser):
    assert check(parser, 'SELECT T3.school FROM frpm AS T1 '
                         'INNER JOIN schools AS T3 ON T1.cdscode = T3.cdscode '
                         'ORDER BY T3.school') == []


def test_join_in_the_middle_of_a_chain_is_not_flagged(parser):
    """다른 조인의 ON에 쓰이면 조인 체인의 고리라 뺄 수 없다."""
    assert check(parser, 'SELECT T3.school FROM frpm AS T1 '
                         'INNER JOIN schools AS T3 ON T1.cdscode = T3.cdscode '
                         'INNER JOIN satscores AS T2 ON T3.cdscode = T2.cds '
                         'WHERE T2.numge1500 > 0') == []


def test_column_without_a_known_copy_is_not_flagged(parser):
    """대체할 사본이 없으면 그 조인은 그 값을 얻는 유일한 경로다."""
    assert check(parser, 'SELECT T3.city FROM frpm AS T1 '
                         'INNER JOIN schools AS T3 ON T1.cdscode = T3.cdscode '
                         'WHERE T1.irc = 1') == []


def test_replacement_table_must_already_be_joined(parser):
    """사본이 있어도 그 테이블이 이 질의에 없으면 조언할 수 없다 —
    다른 조인을 새로 만들라는 말이 되기 때문이다."""
    assert check(parser, 'SELECT T3.school FROM satscores AS T1 '
                         'INNER JOIN schools AS T3 ON T1.cds = T3.cdscode '
                         'WHERE T1.numge1500 > 0') == []


def test_first_from_table_is_never_flagged(parser):
    """FROM의 첫 테이블은 조인이 아니라 기준 테이블이라 뺄 수 없다."""
    assert check(parser, 'SELECT T1."School Name" FROM frpm AS T1 '
                         'INNER JOIN satscores AS T2 ON T1.cdscode = T2.cds '
                         'WHERE T2.numge1500 > 0') == []


def test_subquery_is_skipped(parser):
    """서브쿼리가 있으면 절 단위 IR을 신뢰할 수 없다(QueryIR.has_subquery)."""
    assert check(parser, 'SELECT T3.school FROM frpm AS T1 '
                         'INNER JOIN schools AS T3 ON T1.cdscode = T3.cdscode '
                         'WHERE T1.irc > (SELECT avg(irc) FROM frpm)') == []


def test_no_copies_means_no_findings(parser):
    assert check(parser, 'SELECT T3.school FROM frpm AS T1 '
                         'INNER JOIN schools AS T3 ON T1.cdscode = T3.cdscode', copies={}) == []
