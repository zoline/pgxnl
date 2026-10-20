"""승인된 조인 중 FK 로 이미 드러난 관계는 양방향 모두 [Direct Joins]에서 뺀다 (2026-10-12).

자식 쪽에서만 빼서 부모 블록에 같은 관계가 역방향으로 남았다(california schools 에 frpm·satscores).
"""
from pgxnl.agent.discovery import graph
from pgxnl.agent.discovery.graph import JoinEdge
from pgxnl.cache.schema_vector import SchemaVectorIndex
from pgxnl.connectors.base import ColumnMeta, TableMeta


def _t(name, cols, fks=()):
    return TableMeta(schema="cal", name=name, comment=None,
                     columns=[ColumnMeta(c, "text") for c in cols], foreign_keys=list(fks))


async def test_fk_관계는_양방향으로_빼고_새_관계만_남긴다(monkeypatch):
    edges = [
        JoinEdge(1, "frpm", "cdscode", "schools", "cdscode", "history", 1.0, 1, True, "cal"),
        JoinEdge(2, "satscores", "cds", "schools", "cdscode", "history", 1.0, 1, True, "cal"),
        JoinEdge(3, "frpm", "cdscode", "satscores", "cds", "history", 1.0, 1, True, "cal"),
    ]

    async def fake_list_edges(pool, target, *, only_reviewed=False, schema=None):
        assert schema == "cal" and only_reviewed
        return edges

    monkeypatch.setattr(graph, "list_edges", fake_list_edges)
    sv = SchemaVectorIndex(pool=None, embed_fn=lambda x: x, target_name="T")
    tables = [
        _t("schools", ["cdscode"]),
        _t("frpm", ["cdscode"], [("cdscode", "schools", "cdscode")]),
        _t("satscores", ["cds"], [("cds", "schools", "cdscode")]),
    ]
    out = await sv._approved_joins(tables)
    assert out == {"frpm": [("cdscode", "satscores", "cds")], "satscores": [("cds", "frpm", "cdscode")]}
    assert "schools" not in out
