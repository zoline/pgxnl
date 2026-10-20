"""사용자 저장소. design 문서 §5.13, §7(pgxnl_users) 참고.

API Key는 bcrypt 해시(조회용) + Fernet 암호화(비밀번호 로그인 시 복호화 반환용)
이중으로 저장한다 — bcrypt는 매번 다른 salt를 쓰므로 해시만으로는 동일 키 여부를
직접 비교할 수 없어, api_key_prefix로 후보를 좁힌 뒤 bcrypt.checkpw로 확정한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from pgxnl.auth.security import (
    decrypt_api_key,
    encrypt_api_key,
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_api_key,
    verify_password,
)

_API_KEY_PREFIX_LEN = 15


@dataclass
class UserRecord:
    id: int
    username: str
    email: str | None
    role: str
    created_at: datetime


@dataclass
class UserCredential:
    id: int
    user_id: int
    target_name: str
    db_username: str
    updated_at: datetime


class UserStore:
    def __init__(self, pool: asyncpg.Pool, secret_key: str) -> None:
        self._pool = pool
        self._secret_key = secret_key

    async def get_by_api_key(self, api_key: str) -> UserRecord | None:
        prefix = api_key[:_API_KEY_PREFIX_LEN]
        rows = await self._pool.fetch(
            "SELECT id, username, email, role, api_key_hash, created_at "
            "FROM pgxnl_users WHERE api_key_prefix = $1",
            prefix,
        )
        for r in rows:
            if verify_api_key(api_key, r["api_key_hash"]):
                return UserRecord(
                    id=r["id"], username=r["username"], email=r["email"],
                    role=r["role"], created_at=r["created_at"],
                )
        return None

    async def get_by_id(self, user_id: int) -> UserRecord | None:
        row = await self._pool.fetchrow(
            "SELECT id, username, email, role, created_at FROM pgxnl_users WHERE id = $1",
            user_id,
        )
        return _to_record(row) if row else None

    async def list_users(self) -> list[UserRecord]:
        rows = await self._pool.fetch(
            "SELECT id, username, email, role, created_at FROM pgxnl_users ORDER BY created_at"
        )
        return [_to_record(r) for r in rows]

    async def get_api_key_by_credentials(self, username: str, password: str) -> str | None:
        row = await self._pool.fetchrow(
            "SELECT password_hash, api_key_enc FROM pgxnl_users WHERE username = $1", username
        )
        if row is None or row["password_hash"] is None:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        return decrypt_api_key(row["api_key_enc"], self._secret_key)

    async def create_user(
        self, username: str, *, role: str = "user", email: str | None = None, password: str | None = None,
    ) -> tuple[UserRecord, str, str | None]:
        """신규 사용자 생성. (UserRecord, api_key, password) 반환. password가 None이면 로그인 미지원."""
        api_key = generate_api_key()
        row = await self._pool.fetchrow(
            """
            INSERT INTO pgxnl_users (username, email, role, api_key_hash, api_key_prefix, api_key_enc, password_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, username, email, role, created_at
            """,
            username, email, role,
            hash_api_key(api_key), api_key[:_API_KEY_PREFIX_LEN],
            encrypt_api_key(api_key, self._secret_key),
            hash_password(password) if password else None,
        )
        return _to_record(row), api_key, password

    async def bootstrap_admin(self, username: str, password: str) -> str | None:
        """admin 계정이 없으면 생성 후 api_key 반환. 이미 있으면 None."""
        existing = await self._pool.fetchrow("SELECT id FROM pgxnl_users WHERE username = $1", username)
        if existing is not None:
            return None
        _, api_key, _ = await self.create_user(username, role="admin", password=password)
        return api_key

    async def set_password(self, user_id: int, new_password: str) -> None:
        await self._pool.execute(
            "UPDATE pgxnl_users SET password_hash = $1 WHERE id = $2", hash_password(new_password), user_id
        )

    async def delete_user(self, user_id: int) -> None:
        await self._pool.execute("DELETE FROM pgxnl_users WHERE id = $1", user_id)

    # ── DB 자격증명 (design 문서 신규: 사용자별 대상 DB 접속 계정) ──────────

    async def set_credential(self, user_id: int, target_name: str, db_username: str, db_password: str) -> None:
        await self._pool.execute(
            """
            INSERT INTO pgxnl_user_credentials (user_id, target_name, db_username, password_enc)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, target_name) DO UPDATE
                SET db_username = EXCLUDED.db_username, password_enc = EXCLUDED.password_enc, updated_at = now()
            """,
            user_id, target_name, db_username, encrypt_api_key(db_password, self._secret_key),
        )

    async def get_credential(self, user_id: int, target_name: str) -> tuple[str, str] | None:
        """(db_username, db_password) 복호화 반환. 없으면 None."""
        row = await self._pool.fetchrow(
            "SELECT db_username, password_enc FROM pgxnl_user_credentials WHERE user_id = $1 AND target_name = $2",
            user_id, target_name,
        )
        if row is None:
            return None
        return row["db_username"], decrypt_api_key(row["password_enc"], self._secret_key)

    async def list_credentials(self, user_id: int) -> list[UserCredential]:
        rows = await self._pool.fetch(
            """
            SELECT id, user_id, target_name, db_username, updated_at
            FROM pgxnl_user_credentials WHERE user_id = $1 ORDER BY target_name
            """,
            user_id,
        )
        return [UserCredential(**dict(r)) for r in rows]

    async def delete_credential(self, user_id: int, target_name: str) -> None:
        await self._pool.execute(
            "DELETE FROM pgxnl_user_credentials WHERE user_id = $1 AND target_name = $2", user_id, target_name
        )


def _to_record(row: asyncpg.Record) -> UserRecord:
    return UserRecord(id=row["id"], username=row["username"], email=row["email"], role=row["role"], created_at=row["created_at"])
