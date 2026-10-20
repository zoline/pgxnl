"""SELECT 목록의 완전 중복 컬럼을 하나로 줄인다 (BIRD 465)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import DedupeColumnsRule
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _apply(parser: AntlrPostgresParser, sql: str) -> str:
    edits = DedupeColumnsRule().collect_edits(parser.parse(sql))
    return parser.rewrite(sql, edits) if edits else sql


BIRD_465 = (
    "SELECT COUNT(*) AS count, T1.city, COUNT(*) AS city_count "
    "FROM schools AS T1 INNER JOIN frpm AS T2 ON T1.cdscode = T2.cdscode "
    "WHERE T1.magnet = 1 AND T1.gsserved = 'K-8' "
    'AND T2."NSLP Provision Status" = \'Multiple Provision Types\' GROUP BY T1.city'
)


def test_bird_465는_gold와_같은_두_컬럼이_된다(parser: AntlrPostgresParser) -> None:
    out = _apply(parser, BIRD_465)
    assert out.startswith("SELECT T1.city, COUNT(*) AS city_count FROM")
    assert out.count("COUNT(*)") == 1


def test_별칭이_달라도_같은_식이면_중복이다(parser: AntlrPostgresParser) -> None:
    out = _apply(parser, "SELECT COUNT(*) AS a, x, COUNT(*) AS b FROM t")
    assert out == "SELECT x, COUNT(*) AS b FROM t"


def test_마지막_등장을_남긴다(parser: AntlrPostgresParser) -> None:
    # 앞을 지워야 gold의 (city, count) 순서가 된다 — 결과 비교가 튜플 위치를 본다.
    assert _apply(parser, "SELECT a, b, a FROM t") == "SELECT b, a FROM t"


def test_세_번_중복이면_하나만_남는다(parser: AntlrPostgresParser) -> None:
    out = _apply(parser, "SELECT COUNT(*) AS a, x, COUNT(*) AS b, COUNT(*) AS c FROM t")
    assert out == "SELECT x, COUNT(*) AS c FROM t"


@pytest.mark.parametrize(
    "sql",
    [
        # 중복이 없다
        "SELECT T1.city, COUNT(*) FROM schools AS T1 GROUP BY T1.city",
        # 식이 다르면 중복이 아니다
        "SELECT COUNT(*) AS a, COUNT(T1.id) AS b FROM t AS T1",
        # 컬럼이 하나뿐
        "SELECT a FROM t",
        # 서브쿼리가 있으면 어느 SELECT의 목록인지 모호해 건너뛴다
        "SELECT COUNT(*) AS a, (SELECT 1) AS s, COUNT(*) AS b FROM t",
        # SELECT가 아니다
        "UPDATE t SET a = 1",
    ],
)
def test_손대지_않는_경우(parser: AntlrPostgresParser, sql: str) -> None:
    assert _apply(parser, sql) == sql


def test_공백_차이는_같은_식으로_본다(parser: AntlrPostgresParser) -> None:
    out = _apply(parser, "SELECT COUNT( * ) AS a, x, COUNT(*) AS b FROM t")
    assert out == "SELECT x, COUNT(*) AS b FROM t"


def test_대소문자_차이는_같은_식으로_본다(parser: AntlrPostgresParser) -> None:
    out = _apply(parser, "SELECT count(*) AS a, x, COUNT(*) AS b FROM t")
    assert out == "SELECT x, COUNT(*) AS b FROM t"
