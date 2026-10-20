"""CASE 결과의 예/아니오 문자열을 'YES'/'NO' 로 맞춘다 (BIRD card_games seq 382·379)."""
from __future__ import annotations

import pytest

from pgxnl.agent.canonicalize import YesNoUpperRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def _canon(parser: AntlrPostgresParser, sql: str) -> str:
    return canonicalize_sql(sql, parser, [YesNoUpperRule()])


def test_bird_382_실제_sql(parser: AntlrPostgresParser) -> None:
    sql = ("SELECT CASE WHEN T2.mtgoCode IS NOT NULL THEN 'Yes' ELSE 'No' END FROM cards AS T1 "
           "INNER JOIN sets AS T2 ON T1.setcode = T2.code WHERE T1.name = 'Angel of Mercy'")
    assert _canon(parser, sql) == sql.replace("'Yes'", "'YES'").replace("'No'", "'NO'")


def test_bird_379_집계_case(parser: AntlrPostgresParser) -> None:
    sql = "SELECT CASE WHEN COUNT(*) > 0 THEN 'yes' ELSE 'no' END AS has_korean_version FROM t"
    assert "THEN 'YES' ELSE 'NO' END" in _canon(parser, sql)


def test_중첩_case도_고친다(parser: AntlrPostgresParser) -> None:
    sql = "SELECT CASE WHEN a THEN (CASE WHEN b THEN 'Yes' ELSE 'No' END) ELSE 'x' END FROM t"
    out = _canon(parser, sql)
    assert "THEN 'YES' ELSE 'NO' END" in out
    assert "ELSE 'x' END" in out  # 바깥 CASE 는 yes/no 가 아니라 그대로


@pytest.mark.parametrize("sql", [
    "SELECT CASE WHEN a THEN 'YES' ELSE 'NO' END FROM t",          # 이미 대문자
    "SELECT name FROM t WHERE flag = 'Yes'",                        # 비교값은 데이터와 맞아야 한다
    "SELECT CASE WHEN a THEN 'Yes' ELSE NULL END FROM t",           # yes/no 가 아닌 결과가 섞임
    "SELECT CASE WHEN a THEN 'Yes' ELSE 'Maybe' END FROM t",
    "SELECT CASE WHEN a THEN 'Yesterday' ELSE 'No' END FROM t",
    "SELECT CASE status WHEN 'Yes' THEN 1 ELSE 0 END FROM t",       # WHEN 쪽 값은 결과가 아니다
])
def test_건드리지_않는다(parser: AntlrPostgresParser, sql: str) -> None:
    assert _canon(parser, sql) == sql
