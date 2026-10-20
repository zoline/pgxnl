"""질문이 'List all …' 이면 바깥 SELECT 에 DISTINCT (2026-10-14, card_games 전용)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import DistinctWhenListAllRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


Q = "Which cards are ranked 1st on EDHRec? List all of the cards name and its banned play format."
SQL = ("SELECT T1.name, T2.format FROM cards AS T1 INNER JOIN legalities AS T2 ON T1.uuid = T2.uuid "
       "WHERE T1.edhrecrank = 1 AND T2.status = 'Banned'")


def test_list_all_이면_distinct(parser) -> None:
    out = canonicalize_sql(SQL, parser, [DistinctWhenListAllRule(Q)])
    assert out.startswith("SELECT DISTINCT T1.name, T2.format")


@pytest.mark.parametrize("q", ["List the names of the cards.", "Which cards are ranked 1st?", ""])
def test_표지가_없으면_그대로(parser, q) -> None:
    assert canonicalize_sql(SQL, parser, [DistinctWhenListAllRule(q)]) == SQL


@pytest.mark.parametrize("sql", [
    "SELECT DISTINCT a FROM t",
    "SELECT a, COUNT(*) FROM t GROUP BY a",
    "SELECT COUNT(*) FROM t",
    "SELECT a FROM t ORDER BY b",                     # ORDER BY 가 SELECT 밖 식 → DISTINCT 면 오류
    "SELECT a FROM t UNION SELECT a FROM u",
])
def test_건드리지_않는다(parser, sql) -> None:
    assert canonicalize_sql(sql, parser, [DistinctWhenListAllRule("List all things")]) == sql


def test_order_by_가_select_항목이면_붙인다(parser) -> None:
    out = canonicalize_sql("SELECT a, b FROM t ORDER BY b", parser, [DistinctWhenListAllRule("Lists all items")])
    assert out == "SELECT DISTINCT a, b FROM t ORDER BY b"


@pytest.mark.parametrize("q", [
    "List the names of all the cards in the set Hour of Devastation and find the formats.",
    "Please list the Italian text of all the cards in the set Coldsnap.",
    "List every card.",
])
def test_넓힌_표지(parser, q) -> None:
    assert canonicalize_sql("SELECT a, b FROM t", parser, [DistinctWhenListAllRule(q)]) == "SELECT DISTINCT a, b FROM t"


def test_다른_문장의_all_은_보지_않는다(parser) -> None:
    q = "List the cards. All of them must be black."   # 마침표 너머
    assert canonicalize_sql("SELECT a FROM t", parser, [DistinctWhenListAllRule(q)]) == "SELECT a FROM t"


def test_규칙44와_48이_함께여도_DISTINCT는_한_번(parser) -> None:
    from pgxnl.agent.canonicalize import DistinctSingleColumnRule
    q = "Please list the Italian text of all the cards in the set Coldsnap."
    sql = "SELECT T3.text FROM sets AS T1 INNER JOIN cards AS T2 ON T1.code = T2.setcode INNER JOIN foreign_data AS T3 ON T2.uuid = T3.uuid"
    out = canonicalize_sql(sql, parser, [DistinctSingleColumnRule(None, ["text"]), DistinctWhenListAllRule(q)])
    assert out.startswith("SELECT DISTINCT T3.text") and "DISTINCT DISTINCT" not in out
