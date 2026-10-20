"""build_all(only=...) — 조인 관계는 스키마 전체로 계산하고, 저장은 지정한 테이블만(2026-10-02).
단일 재색인이 테이블 하나만 넘겨 [Direct Joins]가 빠지던 문제의 회귀 테스트."""
from pgxnl.cache.schema_vector import SchemaVectorIndex
from pgxnl.connectors.base import ColumnMeta, TableMeta


def _t(name, cols, fks=()):
    return TableMeta(schema="s", name=name, comment=None,
                     columns=[ColumnMeta(c, "int") for c in cols], foreign_keys=list(fks))


async def test_only_indexes_subset_but_uses_whole_schema_for_joins(monkeypatch):
    sv = SchemaVectorIndex(pool=None, embed_fn=lambda x: x, target_name="T")
    seen = {}

    async def fake_index(table, canonical=None, siblings=None):
        seen[table.name] = siblings
        return True

    async def no_approved(tables):
        return {}

    from pgxnl.settings import settings
    monkeypatch.setattr(settings, "schema_include_sibling_joins", True)  # 기본 false — 켤 때의 동작을 본다
    monkeypatch.setattr(sv, "index_table", fake_index)
    monkeypatch.setattr(sv, "_approved_joins", no_approved)
    # a, b 가 같은 부모 p 를 FK 로 가리킴 → a 와 b 는 형제 조인
    tables = [_t("p", ["id"]), _t("a", ["id", "pid"], [("pid", "p", "id")]),
              _t("b", ["id", "pid"], [("pid", "p", "id")])]
    whole = await SchemaVectorIndex.build_all(sv, tables, only={"a"})
    assert whole == 1 and set(seen) == {"a"}
    with_ctx = seen["a"]

    seen.clear()
    await SchemaVectorIndex.build_all(sv, [tables[1]])   # 예전 방식: 테이블 하나만
    alone = seen["a"]
    assert with_ctx and not alone   # 스키마 전체를 줘야 형제 조인이 계산된다
