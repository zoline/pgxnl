"""별칭 스코프 검사 (`agent/alias_scope.py`).

BIRD 454: 모델이 서브쿼리에 `AS T3`을 붙이고 `WHERE T3.rnk`도 맞게 썼는데 `SELECT`만
안쪽 별칭(`T1.school`)으로 남겼다. 문법은 맞아 generate_sql을 통과하고 검증 계층도
별칭 스코프를 안 봐서, 실행에서야 `missing FROM-clause entry`로 죽었다 — 그때는 ReAct
루프가 끝나 모델이 고칠 기회가 없다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.alias_scope import find_unresolved_aliases
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture
def parser():
    return AntlrPostgresParser()


BAD_454 = (
    "SELECT T1.school FROM ( SELECT T1.school, "
    "RANK() OVER (PARTITION BY T1.county ORDER BY T2.avgscrread DESC) AS rnk "
    "FROM schools AS T1 INNER JOIN satscores AS T2 ON T1.cdscode = T2.cds "
    "WHERE T1.virtual = 'F' ) AS T3 WHERE T3.rnk <= 5"
)


def test_outer_reference_to_inner_alias_is_flagged(parser):
    out = find_unresolved_aliases(parser.parse(BAD_454))
    assert len(out) == 1
    assert out[0].alias == "t1"
    assert out[0].visible == ("t3",)
    assert "t3" in out[0].message()


def test_correct_outer_alias_is_not_flagged(parser):
    sql = ("SELECT T3.school FROM ( SELECT T1.school, RANK() OVER (ORDER BY T2.avgscrread DESC) AS rnk "
           "FROM schools AS T1 INNER JOIN satscores AS T2 ON T1.cdscode = T2.cds ) AS T3 WHERE T3.rnk <= 5")
    assert find_unresolved_aliases(parser.parse(sql)) == []


def test_no_subquery_means_no_check(parser):
    """스코프가 하나뿐이면 이 오류가 날 수 없다."""
    assert find_unresolved_aliases(parser.parse(
        "SELECT T1.school FROM schools AS T1 WHERE T1.county = 'Monterey'")) == []


def test_scalar_subquery_with_its_own_alias_is_fine(parser):
    """서브쿼리가 자기 별칭만 쓰면 정상이다."""
    assert find_unresolved_aliases(parser.parse(
        "SELECT T1.a FROM frpm AS T1 WHERE T1.b > (SELECT avg(T2.b) FROM frpm AS T2)")) == []


def test_bare_table_name_in_outer_from_is_visible(parser):
    """별칭 없이 테이블 이름을 그대로 쓰면 그 이름으로 참조할 수 있다."""
    assert find_unresolved_aliases(parser.parse(
        "SELECT schools.school FROM schools WHERE schools.cdscode IN "
        "(SELECT T1.cdscode FROM frpm AS T1)")) == []


def test_cte_inner_alias_used_outside_is_flagged(parser):
    """Northwind v2 run 565 seq 27: CTE 안의 `c` 를 바깥 SELECT 에서 참조. CTE 본문은
    select_with_parens 가 아니라 처음엔 스코프로 안 봤다."""
    out = find_unresolved_aliases(parser.parse(
        "WITH cr AS (SELECT c.customer_id, SUM(o.freight) AS revenue FROM customers c "
        "JOIN orders o ON o.customer_id = c.customer_id GROUP BY c.customer_id) "
        "SELECT c.company_name, x.revenue FROM cr x"))
    assert [u.alias for u in out] == ["c"]
    assert "x" in out[0].visible and "c" not in out[0].visible


def test_alias_of_sibling_cte_is_flagged(parser):
    """seq 33: 한 CTE 의 `od` 를 다른 CTE 에서 참조 — 형제 스코프는 보이지 않는다."""
    out = find_unresolved_aliases(parser.parse(
        "WITH pr AS (SELECT od.product_id, SUM(od.quantity) AS revenue FROM order_details od "
        "GROUP BY od.product_id), ranked AS (SELECT od.product_id, p.revenue FROM pr p) "
        "SELECT COUNT(*) FROM ranked"))
    assert [u.alias for u in out] == ["od"]


def test_correlated_subquery_sees_outer_alias(parser):
    """안쪽은 바깥 별칭을 볼 수 있다(상관 서브쿼리) — CTE 를 스코프로 넣어도 이건 그대로다."""
    assert find_unresolved_aliases(parser.parse(
        "WITH t AS (SELECT o.customer_id FROM orders o WHERE o.freight > "
        "(SELECT AVG(o2.freight) FROM orders o2 WHERE o2.customer_id = o.customer_id)) "
        "SELECT t.customer_id FROM t")) == []


def test_unqualified_column_is_not_flagged(parser):
    """한정되지 않은 컬럼은 스코프 판정 대상이 아니다 — 파서가 어디 것인지 모른다."""
    assert find_unresolved_aliases(parser.parse(
        "SELECT school FROM ( SELECT T1.school FROM schools AS T1 ) AS T3")) == []
