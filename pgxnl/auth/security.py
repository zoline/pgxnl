"""API 키 / 비밀번호 보안 유틸리티. design 문서 §5.13 참고.

API 키: bcrypt 해시(api_key_hash) + AES-256(Fernet) 암호화 원본(api_key_enc) 이중 보관.
비밀번호: PBKDF2-HMAC-SHA256 (salt:hash 형식).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

import bcrypt
from cryptography.fernet import Fernet


def generate_api_key() -> str:
    return f"pgxnl_{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    return bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()


def verify_api_key(api_key: str, hashed: str) -> bool:
    return bcrypt.checkpw(api_key.encode(), hashed.encode())


def encrypt_api_key(api_key: str, secret_key: str) -> str:
    fernet = Fernet(_derive_fernet_key(secret_key))
    return fernet.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted: str, secret_key: str) -> str:
    fernet = Fernet(_derive_fernet_key(secret_key))
    return fernet.decrypt(encrypted.encode()).decode()


def _derive_fernet_key(secret_key: str) -> bytes:
    import base64

    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split(":")
    salt = bytes.fromhex(salt_hex)
    expected = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return hmac.compare_digest(expected.hex(), digest_hex)
