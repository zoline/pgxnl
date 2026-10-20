"""대상 DB 메타스토어. design 문서 §7(pgxnl_targets) 참고.

DSN은 SECRET_KEY로 Fernet 암호화해 저장한다(비밀번호 포함 문자열이므로).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from pgxnl.auth.security import decrypt_api_key, encrypt_api_key


@dataclass
class TargetRecord:
    id: int
    name: str
    dialect: str
    dsn: str
    created_at: datetime


class TargetStore:
    def __init__(self, pool: asyncpg.Pool, secret_key: str) -> None:
        self._pool = pool
        self._secret_key = secret_key

    async def list_targets(self) -> list[TargetRecord]:
        rows = await self._pool.fetch(
            "SELECT id, name, dialect, dsn_encrypted, created_at FROM pgxnl_targets ORDER BY name"
        )
        return [self._to_record(r) for r in rows]

    async def get(self, name: str) -> TargetRecord | None:
        row = await self._pool.fetchrow(
            "SELECT id, name, dialect, dsn_encrypted, created_at FROM pgxnl_targets WHERE name = $1", name
        )
        return self._to_record(row) if row else None

    async def upsert(self, name: str, dialect: str, dsn: str) -> TargetRecord:
        row = await self._pool.fetchrow(
            """
            INSERT INTO pgxnl_targets (name, dialect, dsn_encrypted)
            VALUES ($1, $2, $3)
            ON CONFLICT (name) DO UPDATE SET dialect = EXCLUDED.dialect, dsn_encrypted = EXCLUDED.dsn_encrypted
            RETURNING id, name, dialect, dsn_encrypted, created_at
            """,
            name, dialect, encrypt_api_key(dsn, self._secret_key),
        )
        return self._to_record(row)

    async def delete(self, name: str) -> None:
        await self._pool.execute("DELETE FROM pgxnl_targets WHERE name = $1", name)

    def _to_record(self, row: asyncpg.Record) -> TargetRecord:
        return TargetRecord(
            id=row["id"], name=row["name"], dialect=row["dialect"],
            dsn=decrypt_api_key(row["dsn_encrypted"], self._secret_key),
            created_at=row["created_at"],
        )
