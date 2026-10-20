"""절 단위 IR 추출 테스트 (docs/pgxnl_antlr_pipeline_design.md §2)."""
from __future__ import annotations

import pytest

from pgxnl.parsing.ir import PredicateNode, normalize_expr
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def ir_of(parser: AntlrPostgresParser, sql: str):
    return parser.to_ir(parser.parse(sql))


def test_select_items_with_alias(parser):
    ir = ir_of(parser, "SELECT name, COUNT(*) AS cnt FROM t")
    assert [i.expr for i in ir.select_items] == ["name", "count(*)"]
    assert [i.alias for i in ir.select_items] == [None, "cnt"]


def test_star_and_distinct(parser):
    ir = ir_of(parser, "SELECT DISTINCT * FROM t")
    assert [i.expr for i in ir.select_items] == ["*"]
    assert ir.distinct is True


def test_where_and_or_tree(parser):
    ir = ir_of(parser, "SELECT a FROM t WHERE x = 1 AND y > 2")
    assert ir.where.op == "AND"
    assert {c.signature() for c in ir.where.flatten_and()} == {"1=x", "y>2"}

    ir_or = ir_of(parser, "SELECT a FROM t WHERE x = 1 OR y > 2")
    assert ir_or.where.op == "OR"


def test_equality_is_commutative_in_signature(parser):
    """`a = b`와 `b = a`는 같은 조건 — 구조 비교가 순서에 흔들리면 안 된다."""
    left = ir_of(parser, "SELECT 1 FROM t WHERE s.cds = x.cds")
    right = ir_of(parser, "SELECT 1 FROM t WHERE x.cds = s.cds")
    assert left.where.signature() == right.where.signature()


def test_inequality_keeps_operand_order(parser):
    """부등호는 교환법칙이 성립하지 않으므로 좌우를 정렬하면 안 된다."""
    node = ir_of(parser, "SELECT 1 FROM t WHERE a > b").where
    assert node.signature() == "a>b"


def test_flat_join_chain(parser):
    """ANTLR이 좌재귀를 평탄화하므로 JOIN 시퀀스를 순서대로 끊어야 한다 —
    중첩으로 가정하면 기본 테이블과 ON 조건이 어긋난다."""
    ir = ir_of(
        parser,
        "SELECT s.name FROM schools s "
        "JOIN satscores t ON s.cds = t.cds "
        "LEFT JOIN frpm f ON f.cds = s.cds",
    )
    assert ir.from_tables == ["schools"]
    assert [(j.join_type, j.table) for j in ir.joins] == [
        ("INNER", "satscores"),
        ("LEFT", "frpm"),
    ]
    assert ir.joins[0].on.signature() == "s.cds=t.cds"
    assert ir.joins[1].on.signature() == "f.cds=s.cds"


def test_join_using(parser):
    ir = ir_of(parser, "SELECT p.a FROM p JOIN q USING (id)")
    assert ir.joins[0].using == ["id"]
    assert ir.joins[0].on is None


def test_comma_join_lists_both_tables(parser):
    ir = ir_of(parser, "SELECT * FROM t1, t2")
    assert ir.from_tables == ["t1", "t2"]
    assert ir.joins == []


def test_group_having_order_limit(parser):
    ir = ir_of(
        parser,
        "SELECT a, COUNT(*) c FROM t GROUP BY a HAVING COUNT(*) > 2 "
        "ORDER BY c DESC, a LIMIT 5 OFFSET 7",
    )
    assert ir.group_by == ["a"]
    assert ir.having.signature() == "count(*)>2"
    assert ir.order_by == [("c", "DESC"), ("a", "ASC")]
    assert (ir.limit, ir.offset) == (5, 7)


def test_cte_outer_query_is_used_not_the_cte_body(parser):
    """WITH절 안의 SELECT를 최상위로 오인하면 안 된다 — 전위 순회상 CTE가 먼저 나온다."""
    ir = ir_of(parser, "WITH totals AS (SELECT cds, SUM(x) v FROM frpm GROUP BY cds) "
                       "SELECT cds FROM totals WHERE v > 10")
    assert ir.from_tables == ["totals"]
    assert [i.expr for i in ir.select_items] == ["cds"]
    assert ir.group_by == []  # CTE 쪽 GROUP BY를 끌어오면 안 된다


def test_subquery_and_setop_flags(parser):
    assert ir_of(parser, "SELECT a FROM t WHERE b IN (SELECT c FROM u)").has_subquery is True
    assert ir_of(parser, "SELECT a FROM t1 UNION SELECT b FROM t2").set_operation == "UNION"
    assert ir_of(parser, "SELECT a FROM t").is_simple is True


def test_non_select_returns_none(parser):
    assert parser.to_ir(parser.parse("UPDATE t SET a = 1")) is None


def test_string_literal_case_is_preserved(parser):
    """식별자는 소문자로 접되 리터럴은 건드리면 안 된다 — 'Seoul'을 'seoul'로 바꾸면
    gold와의 값 비교가 깨진다."""
    assert normalize_expr("City = 'Seoul'") == "city='Seoul'"


def test_normalize_collapses_punctuation_spacing(parser):
    assert normalize_expr("COUNT( * )") == "count(*)"
    assert normalize_expr('"Score"  >  10') == "score>10"


def test_flatten_and_keeps_or_subtree_intact():
    """OR 하위는 순서가 의미를 가지므로 통째로 하나의 잎으로 남아야 한다."""
    or_node = PredicateNode(op="OR", children=[PredicateNode(op="RAW", left="a"),
                                               PredicateNode(op="RAW", left="b")])
    tree = PredicateNode(op="AND", children=[PredicateNode(op="RAW", left="c"), or_node])
    flat = tree.flatten_and()
    assert len(flat) == 2
    assert any(n.op == "OR" for n in flat)
