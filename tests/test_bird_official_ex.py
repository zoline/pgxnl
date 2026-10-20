from decimal import Decimal

from pgxnl.agent.evaluation.bird import _results_equal, results_equal_official


def test_official_ignores_duplicates_strict_does_not():
    gold = [{"f": "legacy"}, {"f": "modern"}]
    pred = [{"f": "legacy"}, {"f": "legacy"}, {"f": "modern"}]
    assert results_equal_official(gold, pred) is True
    assert _results_equal(gold, pred) is False


def test_official_does_not_normalize_case_or_float():
    assert results_equal_official([{"a": "Legal"}], [{"a": "legal"}]) is False
    assert _results_equal([{"a": "Legal"}], [{"a": "legal"}]) is True
    assert results_equal_official([{"x": 0.30000001}], [{"x": 0.3}]) is False


def test_official_equal_numeric_types_and_unhashables():
    assert results_equal_official([{"x": Decimal("1.0")}], [{"x": 1.0}]) is True
    assert results_equal_official([{"a": [1, 2], "j": {"k": 1}}], [{"a": [1, 2], "j": {"k": 1}}]) is True


def test_official_order_independent():
    assert results_equal_official([{"a": 1}, {"a": 2}], [{"a": 2}, {"a": 1}]) is True
