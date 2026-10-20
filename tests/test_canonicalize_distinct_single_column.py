"""DistinctSingleColumnRule — GROUP BY 없는 단일 컬럼 조회에 DISTINCT (2026-10-06, card_games 전용 등록)."""
import pytest

from pgxnl.agent.canonicalize import DistinctSingleColumnRule, canonicalize_sql
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser():
    return AntlrPostgresParser()


def run(parser, sql):
    return canonicalize_sql(sql, parser, [DistinctSingleColumnRule()])


@pytest.mark.parametrize("sql", [
    "SELECT T2.status FROM cards AS T1 INNER JOIN legalities AS T2 ON T1.uuid = T2.uuid WHERE T1.types = 'Artifact'",
    "SELECT name FROM sets WHERE code IN (SELECT setCode FROM set_translations WHERE language = 'Korean')",
    "SELECT T1.name AS n FROM cards AS T1 ORDER BY n",
    "SELECT T1.name FROM cards AS T1 ORDER BY T1.name",
])
def test_adds_distinct(parser, sql):
    out = run(parser, sql)
    assert out.upper().startswith("SELECT DISTINCT ")
    assert out.upper().count("DISTINCT") == 1     # 서브쿼리 안에는 붙이지 않는다


@pytest.mark.parametrize("sql", [
    "SELECT T1.name FROM cards AS T1 ORDER BY T1.convertedmanacost DESC NULLS LAST LIMIT 1",  # PG 오류 회피
    "SELECT DISTINCT T1.name FROM cards AS T1",
    "SELECT T1.name, T1.id FROM cards AS T1",
    "SELECT COUNT(*) FROM cards",
    "SELECT T1.format FROM legalities T1 GROUP BY T1.format",
    "SELECT * FROM cards",
    "SELECT a FROM t UNION SELECT b FROM u",
    "SELECT CAST(SUM(CASE WHEN x=1 THEN 1 ELSE 0 END) AS REAL) / COUNT(id) FROM t",
    "SELECT RANK() OVER (ORDER BY a) FROM t",
])
def test_leaves_alone(parser, sql):
    assert run(parser, sql) == sql


PK = {"cards": {"id"}, "legalities": {"id"}, "pairs": {"a", "b"}}


@pytest.mark.parametrize("sql", [
    "SELECT T1.id FROM cards AS T1 INNER JOIN legalities AS T2 ON T1.uuid = T2.uuid WHERE T2.status = 'Banned'",
    "SELECT id FROM cards WHERE x IS NOT NULL",
    "SELECT T1.a FROM pairs AS T1",                 # 복합 PK 의 일부
])
def test_skips_primary_key_columns(parser, sql):
    assert canonicalize_sql(sql, parser, [DistinctSingleColumnRule(PK)]) == sql


def test_non_pk_still_gets_distinct_with_pk_info(parser):
    sql = "SELECT T2.status FROM cards AS T1 INNER JOIN legalities AS T2 ON T1.uuid = T2.uuid"
    assert canonicalize_sql(sql, parser, [DistinctSingleColumnRule(PK)]).startswith("SELECT DISTINCT")


def test_loader_passes_pk_columns():
    from datetime import datetime

    from pgxnl.agent.canonicalize import load_rules_from_store
    from pgxnl.governance.rules import Rule
    r = Rule(id=44, target_name="BIRD", rule_type="canonicalization", definition={"kind": "distinct_single_column"},
             enabled=True, updated_at=datetime(2026, 10, 6), schema_name="card_games")
    [rule] = load_rules_from_store([r], pk_columns=PK)
    assert rule._pk["cards"] == {"id"}


def test_only_columns_limits_targets(parser):
    rule = [DistinctSingleColumnRule(PK, ["status", "language", "text"])]
    hit = "SELECT T2.status FROM cards AS T1 INNER JOIN legalities AS T2 ON T1.uuid = T2.uuid"
    miss = "SELECT T2.format FROM cards AS T1 INNER JOIN legalities AS T2 ON T1.uuid = T2.uuid"
    assert canonicalize_sql(hit, parser, rule).startswith("SELECT DISTINCT")
    assert canonicalize_sql(miss, parser, rule) == miss
    assert canonicalize_sql("SELECT language FROM foreign_data WHERE name = 'x'", parser, rule).startswith("SELECT DISTINCT")


def test_loader_reads_columns():
    from datetime import datetime

    from pgxnl.agent.canonicalize import load_rules_from_store
    from pgxnl.governance.rules import Rule
    r = Rule(id=44, target_name="BIRD", rule_type="canonicalization",
             definition={"kind": "distinct_single_column", "columns": ["status", "Language"]},
             enabled=True, updated_at=datetime(2026, 10, 6), schema_name="card_games")
    [rule] = load_rules_from_store([r], pk_columns=PK)
    assert rule._only == {"status", "language"}
