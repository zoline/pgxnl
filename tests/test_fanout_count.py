"""1:N 조인으로 부푼 COUNT 감지 (`agent/fanout_count.py`).

Northwind v2 seq 17 실측: 직원별 주문 건수를 `COUNT(o.order_id)` 로 세면서 order_details 를 조인해
2.6배로 부풀었다. 유일성은 실제로는 대상 DB 카탈로그로 보지만, 여기서는 고정 표로 대신한다.
"""
from __future__ import annotations

import asyncio

import pytest

from pgxnl.agent.fanout_count import find_fanout_counts
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

UNIQUE = {
    ("orders", "order_id"): True,
    ("order_details", "order_id"): False,
    ("employees", "employee_id"): True,
    ("orders", "employee_id"): False,
    ("customers", "customer_id"): True,
    ("orders", "customer_id"): False,
}


@pytest.fixture
def parser():
    return AntlrPostgresParser()


def check(parser, sql, table=None):
    stmt = parser.parse(sql)

    async def is_unique(t, c):
        return (UNIQUE if table is None else table).get((t.lower(), c.lower()))

    return asyncio.run(find_fanout_counts(
        parser.to_ir(stmt), alias_to_table=dict(stmt.alias_to_table or {}), is_unique=is_unique,
    ))


def test_1쪽_키를_세며_자식과_조인하면_알린다(parser):
    out = check(parser, "SELECT e.first_name, COUNT(o.order_id) AS order_count FROM employees e "
                        "JOIN orders o ON e.employee_id = o.employee_id "
                        "JOIN order_details od ON o.order_id = od.order_id GROUP BY e.first_name")
    assert len(out) == 1
    assert out[0].table == "orders" and out[0].child_table == "order_details"
    assert "COUNT(DISTINCT" in out[0].message()


def test_스키마를_붙인_테이블은_스키마째로_조회한다(parser):
    # run 560: `public.orders` 로 써서 조회가 실패해 12·17 에서 침묵했다. 이름은 스키마째 넘어간다.
    seen = []
    stmt = parser.parse("SELECT COUNT(o.order_id) FROM public.orders o "
                        "JOIN public.order_details od ON o.order_id = od.order_id")

    async def is_unique(t, c):
        seen.append(t)
        return UNIQUE.get((t.rpartition(".")[2].lower(), c.lower()))

    out = asyncio.run(find_fanout_counts(
        parser.to_ir(stmt), alias_to_table=dict(stmt.alias_to_table or {}), is_unique=is_unique,
    ))
    assert len(out) == 1
    assert "public.orders" in seen


def test_이미_DISTINCT면_조용하다(parser):
    assert not check(parser, "SELECT COUNT(DISTINCT o.order_id) FROM orders o "
                             "JOIN order_details od ON o.order_id = od.order_id")


def test_N쪽에서_부모로_가는_조인은_부풀지_않는다(parser):
    # orders → customers 는 N:1 — 주문 한 행에 고객 하나라 COUNT(o.order_id) 는 그대로다.
    assert not check(parser, "SELECT c.company_name, COUNT(o.order_id) FROM orders o "
                             "JOIN customers c ON o.customer_id = c.customer_id GROUP BY c.company_name")


def test_센_키로_묶었으면_그룹마다_자식_행을_세는_것이다(parser):
    assert not check(parser, "SELECT o.order_id, COUNT(o.order_id) FROM orders o "
                             "JOIN order_details od ON o.order_id = od.order_id GROUP BY o.order_id")


def test_유일성을_모르면_알리지_않는다(parser):
    # 통계도 인덱스도 없으면 판단 불가 — 오탐보다 침묵이 낫다.
    assert not check(parser, "SELECT COUNT(o.order_id) FROM orders o "
                             "JOIN order_details od ON o.order_id = od.order_id", table={})
