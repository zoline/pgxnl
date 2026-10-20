"""통계 어댑터 인터페이스. design 문서 §5.3 / ADR-0007 참고.

향후 다른 DBMS의 옵티마이저 통계 카탈로그를 지원하게 되면 이 인터페이스의 구현체만
추가하면 된다 (예: OracleStatsAdapter -> ALL_TAB_COL_STATISTICS).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


def parse_pg_array(text: str) -> list[Any]:
    """PostgreSQL 배열 리터럴(`{a,"b,c",NULL}`)을 파이썬 리스트로.

    따옴표 없는 `NULL`은 None, 따옴표 안의 `NULL`은 문자열 "NULL"이다 — 값 자체가
    "NULL"이라는 문자열인 경우와 구분해야 한다.
    """
    s = (text or "").strip()
    if not (s.startswith("{") and s.endswith("}")):
        return []
    body = s[1:-1]
    if not body:
        return []
    out: list[Any] = []
    cur: list[str] = []
    quoted = in_quote = escaped = False
    for ch in body:
        if escaped:
            cur.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            in_quote = not in_quote
            quoted = True
        elif ch == "," and not in_quote:
            out.append(_element("".join(cur), quoted))
            cur, quoted = [], False
        else:
            cur.append(ch)
    out.append(_element("".join(cur), quoted))
    return out


def _element(raw: str, quoted: bool) -> Any:
    return raw if quoted else (None if raw.strip().upper() == "NULL" else raw.strip())


def _as_list(value: Any) -> list[Any]:
    """pg_stats 배열 컬럼 값 — 문자열(::text 캐스팅)이면 파싱하고, 이미 리스트면 그대로."""
    if value is None:
        return []
    if isinstance(value, str):
        return parse_pg_array(value)
    return list(value)


@dataclass
class ColumnStats:
    n_distinct: float | None
    null_frac: float | None
    most_common_values: list[Any]
    most_common_freqs: list[float]
    histogram_bounds: list[Any]
    source: str  # 'optimizer_stats' | 'direct_sample'

    @classmethod
    def from_pg_stats(cls, row: dict[str, Any]) -> ColumnStats:
        """pg_stats 한 행을 ColumnStats로. 배열 컬럼은 텍스트로 와도 되고 리스트로 와도 된다.

        `most_common_vals`/`histogram_bounds`는 PostgreSQL에서 `anyarray` 타입이라 드라이버가
        결과 타입을 결정하지 못하는 경우가 있다(asyncpg는 `InternalClientError`로 던진다).
        그래서 조회 쪽에서 `::text`로 캐스팅해 문자열로 받고, 여기서 배열 리터럴을 푼다.
        """
        return cls(
            n_distinct=row.get("n_distinct"),
            null_frac=row.get("null_frac"),
            most_common_values=_as_list(row.get("most_common_vals")),
            most_common_freqs=list(row.get("most_common_freqs") or []),
            histogram_bounds=_as_list(row.get("histogram_bounds")),
            source="optimizer_stats",
        )


class StatsAdapter(ABC):
    @abstractmethod
    async def get_column_stats(self, schema: str, table: str, column: str) -> ColumnStats | None: ...

    @abstractmethod
    async def get_null_frac(self, schema: str, table: str, column: str) -> float | None:
        """NULL 비율만 조회한다. 통계가 없으면(ANALYZE 미실행) None.

        `get_column_stats`와 따로 두는 이유는 최빈값/히스토그램을 같이 읽지 않기
        위해서다 — PostgreSQL에서 그 두 컬럼은 `anyarray` 타입이라 드라이버가 디코딩하지
        못하는 경우가 있고, NULL 비율만 필요한 호출(stats_guard)까지 거기에 묶일 이유가
        없다. 스칼라 하나만 읽으므로 어느 드라이버에서도 안전하다."""

    @abstractmethod
    async def last_analyzed(self, schema: str, table: str) -> float | None:
        """마지막 ANALYZE 시각(epoch seconds). 신선도 판단에 사용."""
