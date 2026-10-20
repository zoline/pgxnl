"""대상 DB 커넥터 인터페이스.

design 문서 §2.3(확장 가능한 골격 유지) / ADR-0001 참고: 지금은 PostgreSQL만
지원하지만, 향후 다른 DBMS를 다시 지원할 가능성을 열어두기 위해 인터페이스는
DBMS 비의존적으로 유지한다. 새 DBMS 지원 시 이 인터페이스의 구현체만 추가하면 된다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnMeta:
    name: str
    data_type: str
    comment: str | None = None
    example_values: list[Any] | None = None
    is_primary_key: bool = False


@dataclass(frozen=True)
class TableMeta:
    schema: str
    name: str
    comment: str | None
    columns: list[ColumnMeta]
    foreign_keys: list[tuple[str, str, str]]  # (local_column, ref_table, ref_column)


@dataclass(frozen=True)
class IndexMeta:
    schema: str
    table: str
    name: str
    is_primary: bool
    is_unique: bool
    definition: str


class BaseConnector(ABC):
    """모든 DBMS 커넥터가 구현해야 하는 최소 인터페이스."""

    dialect: str

    def __init__(self, dsn: str, *, readonly: bool = True) -> None:
        self.dsn = dsn
        self.readonly = readonly

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def list_schemas(self) -> list[str]: ...

    @abstractmethod
    async def list_tables(self, schema: str) -> list[TableMeta]: ...

    @abstractmethod
    async def describe_table(self, schema: str, table: str) -> TableMeta: ...

    @abstractmethod
    async def list_indexes(self, schema: str) -> list[IndexMeta]: ...

    @abstractmethod
    async def execute_readonly(
        self, sql: str, *, row_limit: int | None = None, timeout_seconds: float | None = None,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """schema가 주어지면 해당 스키마를 search_path 맨 앞에 두고 실행한다 — BIRD처럼
        평가 문항마다 대상 스키마(db_id)가 달라지는 경우에 쓴다."""

    @abstractmethod
    async def explain(
        self, sql: str, *, analyze: bool = False, schema: str | None = None, timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """EXPLAIN (FORMAT JSON) 실행계획을 파싱된 dict로 반환한다."""


class UnsupportedDialectError(ValueError):
    """PostgreSQL 이외의 dialect로 커넥터를 등록하려 할 때 발생.

    지금은 PostgreSQL만 지원한다는 범위를 코드 레벨에서 강제하기 위한 가드.
    (design 문서 §3 "커넥터 역할 분리" 참고)
    """
