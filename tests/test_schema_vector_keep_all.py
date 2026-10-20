"""테이블이 적은 스키마는 마진 없이 전부 (2026-10-15)."""
import asyncio

from pgxnl.cache.schema_vector import SchemaVectorIndex


class _Pool:
    def __init__(self, scores):
        self.rows = [{"schema_name": "s", "table_name": f"t{i}", "mschema": "m", "score": sc} for i, sc in enumerate(scores)]

    async def fetch(self, sql, qvec, target, top_k, schema):
        return self.rows[:top_k]


async def _embed(q):
    return [0.0]


def _search(scores, **kw):
    sv = SchemaVectorIndex(_Pool(scores), _embed, "T")
    return asyncio.run(sv.search("q", 10, score_margin=0.10, schema="s", **kw))


def test_three_tables_kept_even_outside_margin():
    assert len(_search([0.7, 0.65, 0.4], keep_all_max=3)) == 3


def test_more_tables_still_filtered():
    assert [c.table for c in _search([0.7, 0.65, 0.4, 0.3], keep_all_max=3)] == ["t0", "t1"]


def test_off_by_default():
    assert len(_search([0.7, 0.65, 0.4])) == 2
