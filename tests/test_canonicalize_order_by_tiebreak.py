"""OrderByTiebreakRule 테스트.

배경: 정렬 기준 하나로 LIMIT 하면 경계 동점에서 어느 행이 잘릴지 정해지지 않는다. Northwind v2
seq 19(10·11위 동률)·32(5회 함께 주문된 11쌍 중 3쌍)가 이것으로 틀렸고, gold 는 결과의 이름 컬럼을
오름차순으로 붙여 가른다.
"""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import OrderByNullsRule, OrderByTiebreakRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def canon(parser, sql: str) -> str:
    return canonicalize_sql(sql, parser, [OrderByTiebreakRule()])


def test_이름_컬럼을_동점_기준으로_붙인다(parser):
    assert canon(parser, "SELECT p.product_name, SUM(od.quantity) AS q FROM order_details od "
                         "JOIN products p ON od.product_id = p.product_id GROUP BY p.product_name "
                         "ORDER BY q DESC LIMIT 10").endswith("ORDER BY q DESC , p.product_name LIMIT 10")


def test_여러_컬럼은_SELECT_순서대로(parser):
    out = canon(parser, "SELECT p1.name, p2.name, COUNT(*) AS n FROM t p1, t p2 "
                        "GROUP BY p1.name, p2.name ORDER BY n DESC LIMIT 10")
    assert out.endswith("ORDER BY n DESC , p1.name, p2.name LIMIT 10")


def test_이미_정렬_키에_있으면_붙이지_않는다(parser):
    sql = "SELECT product_name, unit_price FROM products ORDER BY unit_price DESC, product_name LIMIT 10"
    assert canon(parser, sql) == sql


def test_위치_번호_정렬도_알아본다(parser):
    out = canon(parser, "SELECT product_name, unit_price FROM products ORDER BY 2 DESC LIMIT 3")
    assert out.endswith("ORDER BY 2 DESC , product_name LIMIT 3")


@pytest.mark.parametrize("sql", [
    "SELECT product_name FROM products ORDER BY unit_price DESC",              # LIMIT 없음
    "SELECT * FROM products ORDER BY unit_price DESC LIMIT 3",                 # 무엇이 붙을지 모름
    "SELECT COUNT(*) AS n FROM products ORDER BY n DESC LIMIT 3",              # 단순 컬럼 없음
    "SELECT a FROM t UNION SELECT a FROM u ORDER BY a LIMIT 3",                # 복합 쿼리
])
def test_건드리지_않는_경우(parser, sql):
    assert canon(parser, sql) == sql


def test_NULLS_LAST_와_함께_써도_순서가_맞다(parser):
    # 두 규칙 모두 정렬 끝에 글자를 넣는다 — NULLS LAST 가 원래 키에 붙어야 한다.
    out = canonicalize_sql("SELECT name, score FROM t ORDER BY score DESC LIMIT 5", parser,
                           [OrderByNullsRule("desc_last"), OrderByTiebreakRule()])
    assert out == "SELECT name, score FROM t ORDER BY score DESC NULLS LAST , name LIMIT 5"
