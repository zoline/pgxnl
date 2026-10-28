"""그룹별 1위를 LIMIT 1 로 자른 SQL 판정 (Northwind L4-06, 2026-10-28)."""
import pytest

from pgxnl.agent.per_group_top import find_per_group_top
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

Q = "국가별로 매출 1위 고객사의 국가, 회사명, 매출을 매출이 높은 순서로 보여주세요."
L4_06 = ("SELECT c.country, c.company_name, ROUND(CAST(SUM(od.unit_price * od.quantity * (1 - od.discount)) AS NUMERIC), 2) AS revenue "
         "FROM customers c JOIN orders o ON o.customer_id = c.customer_id JOIN order_details od ON od.order_id = o.order_id "
         "GROUP BY c.country, c.company_name ORDER BY revenue DESC NULLS LAST, c.country, c.company_name LIMIT 1")


@pytest.fixture(scope="module")
def parser():
    return AntlrPostgresParser()


def _f(parser, sql, q=Q):
    return find_per_group_top(parser.parse(sql), q)


def test_northwind_l4_06(parser):
    assert _f(parser, L4_06)


def test_english_question(parser):
    assert _f(parser, L4_06, "For each country, which customer has the highest revenue?")


@pytest.mark.parametrize("sql", [
    # 그룹 하나를 고르는 질문 — GROUP BY 키가 하나
    "SELECT c.category_name, SUM(x) AS r FROM t c GROUP BY c.category_name ORDER BY r DESC LIMIT 1",
    # 이미 PARTITION BY 로 그룹마다 1위를 고름 — 바깥에 LIMIT 1 없음
    "WITH r AS (SELECT country, company_name, RANK() OVER (PARTITION BY country ORDER BY s DESC) AS rk FROM t) "
    "SELECT country, company_name FROM r WHERE rk = 1",
    # 상위 N
    "SELECT country, company_name, SUM(x) AS r FROM t GROUP BY country, company_name ORDER BY r DESC LIMIT 10",
])
def test_untouched(parser, sql):
    assert not _f(parser, sql)


def test_question_without_group_or_top_is_untouched(parser):
    assert not _f(parser, L4_06, "매출 1위 고객사의 국가, 회사명, 매출을 보여주세요.")
    assert not _f(parser, L4_06, "국가별로 고객사의 매출을 보여주세요.")
