"""M-Schema 직렬화 단위 테스트.

LLM/DB 의존이 없는 순수 코드 경로라 §2.2 원칙대로 일반 pytest로 검증 가능하다.
"""
from pgxnl.agent.mschema import to_light_doc, to_mschema
from pgxnl.connectors.base import ColumnMeta, TableMeta


def _sample_table() -> TableMeta:
    return TableMeta(
        schema="public",
        name="orders",
        comment="주문 테이블",
        columns=[
            ColumnMeta(name="id", data_type="integer", is_primary_key=True, example_values=[1, 2]),
            ColumnMeta(
                name="status", data_type="text", comment="주문 상태",
                example_values=["A", "A", "C", "D", "A", "C"],
            ),
        ],
        foreign_keys=[("customer_id", "customers", "id")],
    )


def test_light_doc_excludes_example_values():
    doc = to_light_doc(_sample_table())
    assert "orders" in doc
    assert "id" in doc and "status" in doc
    assert "example" not in doc.lower()  # 경량 표현에는 값 예시가 없어야 함


def test_mschema_includes_examples_deduped_and_limited():
    mschema = to_mschema(_sample_table())
    assert "【Foreign keys】" in mschema
    assert "orders.customer_id=customers.id" in mschema
    # status 컬럼 값 예시는 중복 제거되어 ['A', 'C', 'D'] 순서로 최대 3개만 남아야 함
    assert "example: [A, C, D]" in mschema


def test_mschema_pk_flag():
    mschema = to_mschema(_sample_table())
    lines = mschema.split("\n")
    # lines[0] = "# Table: ...", lines[1] = "[", lines[2] = id 컬럼 정의
    assert "PK" in lines[2]


def _wide_table(n_columns: int) -> TableMeta:
    return TableMeta(
        schema="public",
        name="match",
        comment=None,
        columns=[ColumnMeta(name=f"col{i}", data_type="text") for i in range(n_columns)],
        foreign_keys=[],
    )


def test_light_doc_caps_column_count_for_wide_tables():
    # 실제로 겪은 회귀 케이스: BIRD european_football_2.Match(컬럼 100개+)를 그대로
    # 다 나열하면 IBM granite-embedding-278m-multilingual의 512 토큰 제한을 넘겨
    # 임베딩 API가 500 오류를 냈다. 앞쪽 40개만 포함하고 나머지는 개수만 요약해야 한다.
    doc = to_light_doc(_wide_table(120))
    assert "col0" in doc and "col39" in doc
    assert "col40" not in doc  # 캡을 넘긴 컬럼은 포함되지 않아야 함
    assert "생략" in doc  # 생략됐다는 표시가 있어야 함


def test_light_doc_no_truncation_marker_under_cap():
    doc = to_light_doc(_wide_table(5))
    assert "생략" not in doc
    assert "col4" in doc


def test_mschema_original_fk_and_join_paths():
    """M-Schema 원형 【Foreign keys】 a=b, 확장 【Join paths】 를 그 뒤에 (2026-10-15)."""
    out = to_mschema(_sample_table(), siblings=[("customer_id", "payments", "customer_id")])
    assert out.endswith("【Foreign keys】\norders.customer_id=customers.id\n【Join paths】\norders.customer_id=payments.customer_id")
