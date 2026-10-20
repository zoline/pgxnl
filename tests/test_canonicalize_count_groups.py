"""How many + 그룹별 집계만 → 그룹 수 (BIRD codebase_community 320, 2026-10-15)."""
import pytest

from pgxnl.agent.canonicalize import CountGroupsRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser

Q = "How many users are awarded with more than 5 badges?"


@pytest.fixture(scope="module")
def parser():
    return AntlrPostgresParser()


def test_bird_320(parser):
    sql = "SELECT COUNT(userid) FROM badges GROUP BY userid HAVING COUNT(name) > 5"
    assert canonicalize_sql(sql, parser, [CountGroupsRule(Q)]) == f"SELECT COUNT(*) FROM ({sql}) AS t"


@pytest.mark.parametrize("q,sql", [
    (Q, "SELECT userid, COUNT(*) FROM badges GROUP BY userid"),              # 그룹 키가 있다
    (Q, "SELECT COUNT(*) FROM badges"),                                       # GROUP BY 없음
    (Q, "SELECT COUNT(*) FROM badges GROUP BY userid ORDER BY 1 DESC LIMIT 1"),
    ("How many badges does each user have?", "SELECT COUNT(*) FROM badges GROUP BY userid"),
    ("List users with more than 5 badges", "SELECT COUNT(*) FROM badges GROUP BY userid"),
])
def test_untouched(parser, q, sql):
    assert canonicalize_sql(sql, parser, [CountGroupsRule(q)]) == sql
