"""SELECT 목록의 스칼라 서브쿼리가 2컬럼 이상이면 잡는다 (BIRD 465)."""
from __future__ import annotations

import pytest

from pgxnl.agent.scalar_subquery import find_multicolumn_scalar_subqueries
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _find(parser: AntlrPostgresParser, sql: str):
    return find_multicolumn_scalar_subqueries(parser.parse(sql))


BIRD_465 = """
SELECT
  (SELECT COUNT(*) FROM schools AS T1 INNER JOIN frpm AS T2 ON T1.cdscode = T2.cdscode
     WHERE T1.magnet = 1 AND T1.gsoffered = 'K-8'
       AND T2."NSLP Provision Status" = 'Multiple Provision Types') AS multiple_provision_count,
  (SELECT COUNT(DISTINCT T1.city) FROM schools AS T1 WHERE T1.gsoffered = 'K-8') AS number_of_cities,
  (SELECT T1.city, COUNT(*) AS school_count FROM schools AS T1
     WHERE T1.gsoffered = 'K-8' GROUP BY T1.city ORDER BY T1.city) AS city_school_counts
"""


def test_bird_465_실제_실패_sql을_잡는다(parser: AntlrPostgresParser) -> None:
    found = _find(parser, BIRD_465)
    assert len(found) == 1
    assert found[0].label == "city_school_counts"
    assert len(found[0].columns) == 2


def test_메시지가_실제_오류문구를_담는다(parser: AntlrPostgresParser) -> None:
    msg = _find(parser, BIRD_465)[0].message()
    assert "subquery must return only one column" in msg
    assert "city_school_counts" in msg


def test_별칭이_없으면_원문을_보여준다(parser: AntlrPostgresParser) -> None:
    found = _find(parser, "SELECT (SELECT a, b FROM t) FROM u")
    assert len(found) == 1
    assert found[0].label.startswith("(SELECT a, b")


@pytest.mark.parametrize(
    "sql",
    [
        # FROM 절 서브쿼리는 여러 컬럼이 정상이다
        "SELECT x.a FROM (SELECT a, b FROM t) AS x",
        # 컬럼 하나짜리 스칼라 서브쿼리
        "SELECT (SELECT count(*) FROM t) AS n, c FROM u",
        # 서브쿼리가 아예 없다
        "SELECT city, count(*) FROM schools GROUP BY city",
        # IN 서브쿼리는 SELECT 목록이 아니다
        "SELECT a FROM t WHERE a IN (SELECT b FROM u)",
        # 스칼라 서브쿼리 안의 FROM 서브쿼리가 2컬럼 — 바깥은 1컬럼이라 정상
        "SELECT (SELECT n FROM (SELECT a, b AS n FROM t) AS z LIMIT 1) AS s FROM u",
        # EXISTS 는 컬럼 개수를 따지지 않는다
        "SELECT a FROM t WHERE EXISTS (SELECT 1, 2 FROM u)",
    ],
)
def test_정상_sql은_잡지_않는다(parser: AntlrPostgresParser, sql: str) -> None:
    assert _find(parser, sql) == []


def test_서브쿼리가_둘이면_둘_다_돌려준다(parser: AntlrPostgresParser) -> None:
    sql = "SELECT (SELECT a, b FROM t) AS x, (SELECT c, d FROM u) AS y FROM v"
    found = _find(parser, sql)
    assert [f.label for f in found] == ["x", "y"]


def test_stmt가_없으면_빈_리스트(parser: AntlrPostgresParser) -> None:
    assert find_multicolumn_scalar_subqueries(None) == []
