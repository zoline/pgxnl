"""오답 카테고리 진단 테스트 (docs/pgxnl_antlr_pipeline_design.md §6)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from pgxnl.agent.evaluation import diagnose as D
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


@pytest.fixture(scope="module")
def parser() -> AntlrPostgresParser:
    return AntlrPostgresParser()


def category(parser, gold: str, pred: str | None, ex_pass: bool | None = False) -> str:
    return D.diagnose_item(parser, seq=0, gold_sql=gold, pred_sql=pred, ex_pass=ex_pass).category


def test_passing_item_is_match(parser):
    assert category(parser, "SELECT a FROM t", "SELECT a FROM t", ex_pass=True) == D.MATCH


def test_missing_sql_is_its_own_category(parser):
    """SQL을 아예 못 낸 경우를 SEMANTIC_WRONG에 섞으면 '진짜 논리 오류' 비중이 부풀려진다."""
    assert category(parser, "SELECT a FROM t", None) == D.NO_SQL
    assert category(parser, "SELECT a FROM t", "   ") == D.NO_SQL


def test_syntax_error(parser):
    assert category(parser, "SELECT a FROM t", "SELEC a FROM") == D.SYNTAX


def test_projection_only_difference(parser):
    """컬럼만 다른 경우 — 질문 텍스트에서 불필요한 컬럼을 잡아낼 수 있는 유형."""
    assert category(
        parser, "SELECT a FROM t WHERE x = 1", "SELECT a, b FROM t WHERE x = 1"
    ) == D.PROJECTION_MISMATCH


def test_predicate_only_difference(parser):
    assert category(
        parser, "SELECT a FROM t WHERE x = 1", "SELECT a FROM t WHERE x = 2"
    ) == D.PREDICATE_MISMATCH


def test_join_only_difference(parser):
    assert category(
        parser,
        "SELECT a FROM t JOIN u ON t.id = u.id",
        "SELECT a FROM t JOIN v ON t.id = v.id",
    ) == D.JOIN_MISMATCH


def test_groupby_only_difference(parser):
    assert category(
        parser, "SELECT a FROM t GROUP BY a", "SELECT a FROM t GROUP BY a, b"
    ) == D.GROUPBY_MISMATCH


def test_multiple_clauses_wrong_is_semantic(parser):
    assert category(
        parser,
        "SELECT a FROM t WHERE x = 1 GROUP BY a",
        "SELECT b FROM t WHERE x = 2 GROUP BY b",
    ) == D.SEMANTIC_WRONG


def test_identical_structure_but_failed_execution_is_value_mismatch(parser):
    """구조가 같은데 EX가 틀렸다면 값/타입/카디널리티 문제 — 여러 절이 어긋난
    진짜 논리 오류(SEMANTIC_WRONG)와 섞으면 개선 방향이 정반대로 나온다."""
    assert category(parser, "SELECT a FROM t", "SELECT a FROM t") == D.VALUE_MISMATCH


def test_subquery_is_uncomparable(parser):
    """서브쿼리가 끼면 절 단위 비교를 신뢰할 수 없다 — 오분류하지 말고 따로 센다(§8)."""
    assert category(
        parser, "SELECT a FROM t WHERE b IN (SELECT c FROM u)", "SELECT a FROM t WHERE b = 1"
    ) == D.UNCOMPARABLE


def test_order_ignored_when_gold_has_none(parser):
    """gold에 ORDER BY가 없으면 pred의 정렬 차이는 오답 사유가 아니다 (§3.2)."""
    diff = D.compare_ir(
        _ir(parser, "SELECT a FROM t ORDER BY a"), _ir(parser, "SELECT a FROM t")
    )
    assert diff.order_limit is True


def test_join_order_does_not_matter(parser):
    """조인 순서를 바꿔 써도 같은 질의다 — 기본 테이블과 조인 대상을 합쳐 비교한다."""
    diff = D.compare_ir(
        _ir(parser, "SELECT x FROM u JOIN t ON t.id = u.id"),
        _ir(parser, "SELECT x FROM t JOIN u ON u.id = t.id"),
    )
    assert diff.join is True


def test_alias_is_ignored_in_projection(parser):
    diff = D.compare_ir(
        _ir(parser, "SELECT COUNT(*) AS n FROM t"), _ir(parser, "SELECT COUNT(*) FROM t")
    )
    assert diff.projection is True


def test_report_counts_and_renders():
    @dataclass
    class Item:
        seq: int
        gold_sql: str
        pred_sql: str | None
        ex_pass: bool | None
        difficulty: str = "simple"

    items = [
        Item(0, "SELECT a FROM t", "SELECT a FROM t", True),
        Item(1, "SELECT a FROM t", None, False),
        Item(2, "SELECT a FROM t WHERE x = 1", "SELECT a, b FROM t WHERE x = 1", False),
    ]
    report = D.diagnose_items(items)
    assert report.total == 3
    assert report.counts[D.MATCH] == 1
    assert report.counts[D.NO_SQL] == 1
    assert report.counts[D.PROJECTION_MISMATCH] == 1
    assert "총 3문항" in report.render()


def _ir(parser, sql):
    return parser.to_ir(parser.parse(sql))
