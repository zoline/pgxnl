"""pg_stats 배열 리터럴 파서 테스트.

`most_common_vals`/`histogram_bounds`는 PostgreSQL에서 `anyarray`라 asyncpg가 결과 타입을
결정하지 못한다 — 실측(2026-09-07) 결과 `get_column_stats()`가 **어떤 컬럼으로 호출해도**
`InternalClientError`로 실패했고, 그래서 ReAct의 collect_stats 도구가 통계를 한 번도
돌려준 적이 없었다. ::text로 캐스팅해 받고 여기서 푼다.
"""
from pgxnl.agent.stats.base import ColumnStats, parse_pg_array


def test_simple_values():
    assert parse_pg_array("{a,b,c}") == ["a", "b", "c"]


def test_empty_array():
    assert parse_pg_array("{}") == []


def test_not_an_array_returns_empty():
    for bad in ("", "   ", "abc", None):
        assert parse_pg_array(bad) == []


def test_quoted_values_keep_commas_and_spaces():
    # 값 안의 쉼표로 쪼개지면 안 된다 — 'High Schools (Public)' 같은 값이 흔하다.
    assert parse_pg_array('{"High Schools (Public)","Continuation High Schools"}') == [
        "High Schools (Public)", "Continuation High Schools",
    ]
    assert parse_pg_array('{"a,b",c}') == ["a,b", "c"]


def test_unquoted_null_is_none_but_quoted_null_is_text():
    # 값 자체가 "NULL"이라는 문자열인 경우와 구분해야 한다.
    assert parse_pg_array("{a,NULL,b}") == ["a", None, "b"]
    assert parse_pg_array('{a,"NULL",b}') == ["a", "NULL", "b"]


def test_escaped_quote_and_backslash():
    assert parse_pg_array(r'{"say \"hi\"","back\\slash"}') == ['say "hi"', "back\\slash"]


def test_from_pg_stats_accepts_text_arrays():
    stats = ColumnStats.from_pg_stats({
        "n_distinct": 4.0, "null_frac": 0.25,
        "most_common_vals": '{"High Schools (Public)","Continuation High Schools"}',
        "most_common_freqs": [0.7, 0.2],
        "histogram_bounds": "{1,5,9}",
    })
    assert stats.most_common_values == ["High Schools (Public)", "Continuation High Schools"]
    assert stats.most_common_freqs == [0.7, 0.2]
    assert stats.histogram_bounds == ["1", "5", "9"]
    assert stats.source == "optimizer_stats"


def test_from_pg_stats_still_accepts_native_lists():
    # 드라이버가 배열을 그대로 줄 수 있는 경로(다른 DBMS 어댑터 등)도 깨지 않는다.
    stats = ColumnStats.from_pg_stats({
        "n_distinct": 2.0, "null_frac": 0.0,
        "most_common_vals": ["a", "b"], "most_common_freqs": [0.6, 0.4],
        "histogram_bounds": None,
    })
    assert stats.most_common_values == ["a", "b"]
    assert stats.histogram_bounds == []
