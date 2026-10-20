"""ANTLR4 PostgreSQL 파서(referenced_tables 추출) 단위 테스트.

배경: WITH절(CTE)로 정의한 이름이 실제 카탈로그 테이블로 오인돼, 검증
계층(§5.9 _bind_catalog)이 정상적인 SQL을 "존재하지 않는 테이블 참조"로
부당하게 거부하는 걸 실측으로 확인했다(BIRD 문항 465번,
`WITH total AS (...) SELECT ... FROM total`).
"""
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser


def test_cte_name_excluded_from_referenced_tables():
    parser = AntlrPostgresParser()
    sql = (
        "WITH total AS (SELECT COUNT(*) AS c FROM frpm) "
        "SELECT * FROM total"
    )
    stmt = parser.parse(sql)
    assert "total" not in stmt.referenced_tables
    assert "frpm" in stmt.referenced_tables


def test_multiple_ctes_and_nested_cte_reference_excluded():
    # 뒤에 정의된 CTE(city_counts)가 앞서 정의된 CTE(total)를 참조해도(중첩) 둘 다
    # referenced_tables에서 빠져야 한다 — WITH절 선언 순서상 total이 먼저 잡히므로
    # city_counts 정의 안의 FROM total도 정상적으로 걸러진다.
    parser = AntlrPostgresParser()
    sql = (
        "WITH total AS (SELECT COUNT(*) AS c FROM frpm), "
        "city_counts AS (SELECT * FROM total) "
        "SELECT * FROM city_counts"
    )
    stmt = parser.parse(sql)
    assert "total" not in stmt.referenced_tables
    assert "city_counts" not in stmt.referenced_tables
    assert "frpm" in stmt.referenced_tables


def test_plain_select_without_cte_still_works():
    parser = AntlrPostgresParser()
    stmt = parser.parse("SELECT * FROM schools T1 JOIN satscores T2 ON T1.cdscode = T2.cds")
    assert "schools" in stmt.referenced_tables
    assert "satscores" in stmt.referenced_tables
