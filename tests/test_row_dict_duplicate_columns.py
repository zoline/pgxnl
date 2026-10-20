"""이름이 같은 컬럼을 잃지 않는다 (codebase_community 323 채점 버그, 2026-10-16)."""
from pgxnl.connectors.postgresql import _row_dict


class _Rec:
    def __init__(self, pairs):
        self._p = pairs

    def keys(self):
        return [k for k, _ in self._p]

    def values(self):
        return [v for _, v in self._p]


def test_duplicate_names_kept_in_order():
    assert _row_dict(_Rec([("avg", 1), ("avg", 2), ("avg", 3)])) == {"avg": 1, "avg#2": 2, "avg#3": 3}


def test_unique_names_unchanged():
    assert _row_dict(_Rec([("a", 1), ("b", 2)])) == {"a": 1, "b": 2}
