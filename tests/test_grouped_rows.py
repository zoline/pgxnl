"""그룹별 집계만 여러 행 나오는 SQL 판정 (BIRD codebase_community 320·323, 2026-10-16)."""
import pytest

from pgxnl.agent.grouped_rows import find_grouped_rows
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser():
    return AntlrPostgresParser()


def _f(parser, sql, q="What is the average of the up votes for users creating more than 10 posts?"):
    return find_grouped_rows(parser.parse(sql), q)


def test_bird_323(parser):
    sql = ("SELECT CAST(SUM(T2.upvotes) AS REAL) / COUNT(T1.owneruserid) AS avg_upvotes, AVG(T2.age) AS avg_age "
           "FROM posts AS T1 INNER JOIN users AS T2 ON T1.owneruserid = T2.id GROUP BY T1.owneruserid HAVING COUNT(T1.owneruserid) > 10")
    assert _f(parser, sql)


def test_bird_320(parser):
    assert _f(parser, "SELECT COUNT(userid) FROM badges GROUP BY userid HAVING COUNT(name) > 5", "How many users …?")


@pytest.mark.parametrize("sql", [
    "SELECT userid, COUNT(*) FROM badges GROUP BY userid",                       # 그룹 키가 SELECT 에 있다
    "SELECT AVG(age) FROM users",                                                 # GROUP BY 없음
    "SELECT COUNT(*) FROM badges GROUP BY userid ORDER BY 1 DESC LIMIT 1",        # 상위 N
    "SELECT AVG(x) FROM (SELECT COUNT(*) AS x FROM badges GROUP BY userid) AS t", # 이미 바깥에서 집계
])
def test_untouched(parser, sql):
    assert not _f(parser, sql)


def test_per_group_question_untouched(parser):
    assert not _f(parser, "SELECT COUNT(*) FROM badges GROUP BY userid", "How many badges does each user have?")
