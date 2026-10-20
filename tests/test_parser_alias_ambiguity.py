"""별칭 바인딩 충돌 감지 (`ParsedStatement.ambiguous_aliases`).

`alias_to_table`은 스코프를 구분하지 않는 평면 dict라, 서브쿼리가 바깥과 같은 별칭을
다른 테이블에 쓰면 안쪽이 바깥을 조용히 덮어쓴다. 컬럼을 고쳐 쓰는 규칙(CanonicalColumnRule)이
이 경우를 피할 수 있도록 충돌 자체를 노출한다.
"""
from __future__ import annotations

import pytest

from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture
def parser():
    return AntlrPostgresParser()


def test_distinct_aliases_are_not_ambiguous(parser):
    st = parser.parse('SELECT T2.school FROM frpm AS T1 JOIN schools AS T2 '
                      'ON T1.cdscode = T2.cdscode WHERE T1.x > (SELECT AVG(T3.y) FROM frpm AS T3)')
    assert st.ambiguous_aliases == frozenset()


def test_same_alias_same_table_is_not_ambiguous(parser):
    """별칭을 재사용해도 같은 테이블이면 바인딩이 하나뿐이라 위험하지 않다."""
    st = parser.parse('SELECT T1.a FROM frpm AS T1 WHERE T1.b > (SELECT max(T1.c) FROM frpm AS T1)')
    assert st.ambiguous_aliases == frozenset()


def test_same_alias_different_tables_is_ambiguous(parser):
    st = parser.parse('SELECT a.x FROM frpm AS a WHERE a.y > (SELECT max(a.z) FROM schools AS a)')
    assert st.ambiguous_aliases == frozenset({"a"})
    # 평면 dict는 안쪽 바인딩만 남긴다 — 이것이 감지가 필요한 이유다.
    assert st.alias_to_table["a"] == "schools"


def test_no_subquery_has_no_ambiguity(parser):
    st = parser.parse('SELECT T1.a, T2.b FROM frpm AS T1 JOIN schools AS T2 ON T1.cdscode = T2.cdscode')
    assert st.ambiguous_aliases == frozenset()
