from pgxnl.agent.designlab.schema_text import render_schema, render_table
from pgxnl.connectors.base import ColumnMeta, TableMeta


def _t(name, cols, fks=(), comment=None):
    return TableMeta(schema="s", name=name, comment=comment, columns=cols, foreign_keys=list(fks))


def test_render_table_marks_pk_fk_and_comments():
    t = _t("orders", [
        ColumnMeta("id", "integer", is_primary_key=True),
        ColumnMeta("cust_id", "integer", comment="고객"),
    ], fks=[("cust_id", "customers", "id")], comment="주문")
    out = render_table(t)
    assert out.splitlines()[0] == "TABLE orders  -- 주문"
    assert "  id integer [PK]" in out
    assert "  cust_id integer [FK→customers.id]  -- 고객" in out


def test_render_schema_omits_tables_past_limit_in_order():
    big = [ColumnMeta(f"c{i}", "text") for i in range(20)]
    tables = [_t("a", big), _t("b", big), _t("c", [ColumnMeta("x", "int")])]
    one = len(render_table(tables[0])) + 2
    st = render_schema(tables, limit=one + 10)
    assert st.included == 1
    # 뒤 테이블이 작아서 들어갈 수 있어도 순서를 지켜 함께 뺀다 — 중간이 비면 FK가 끊겨 보인다
    assert st.omitted == ["b", "c"]
    assert "TABLE a" in st.text and "TABLE c" not in st.text


def test_render_schema_fits_all():
    st = render_schema([_t("a", [ColumnMeta("x", "int")])])
    assert st.included == 1 and st.omitted == []
