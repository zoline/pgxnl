"""seed/*.json 의 기준 정보를 시스템 DB에 넣는다.

    python tools/seed_import.py              # 이미 있는 항목(자연 키 일치)은 건너뜀
    python tools/seed_import.py --replace    # 이미 있는 항목은 seed 내용으로 덮어씀
    python tools/seed_import.py --dry-run    # 넣지 않고 개수만

시스템 DB 스키마(db/schema.sql)는 서버를 한 번 띄우면 적용된다 — 그 뒤에 실행한다.
seed 의 id 가 비어 있으면 그 번호로 넣어 문서의 "규칙 44" 같은 번호가 그대로 맞게 한다.
"""
from __future__ import annotations

import argparse
import asyncio
import json

import asyncpg

from pgxnl.settings import settings
from seed_common import SEED_DIR, TABLES


def _key_sql(spec: dict, offset: int) -> str:
    parts = []
    for i, c in enumerate(spec["key"], start=offset):
        cast = "::jsonb" if c in spec["jsonb"] else ""
        parts.append(f"{c} IS NOT DISTINCT FROM ${i}{cast}")
    return " AND ".join(parts)


def _val(spec: dict, row: dict, c: str):
    v = row.get(c)
    return json.dumps(v, ensure_ascii=False) if c in spec["jsonb"] and v is not None else v


async def import_table(conn: asyncpg.Connection, name: str, spec: dict, replace: bool, dry_run: bool) -> None:
    path = SEED_DIR / f"{name}.json"
    if not path.exists():
        print(f"{name}: seed 파일 없음, 건너뜀")
        return
    rows = json.loads(path.read_text(encoding="utf-8"))
    table = spec["table"]
    data_cols = [c for c in spec["columns"] if c != "id"]
    added = updated = skipped = 0
    for row in rows:
        existing = await conn.fetchval(
            f"SELECT id FROM {table} WHERE {_key_sql(spec, 1)} LIMIT 1",
            *[_val(spec, row, c) for c in spec["key"]])
        if existing is not None:
            if not replace:
                skipped += 1
                continue
            sets = ", ".join(f"{c} = ${i}{'::jsonb' if c in spec['jsonb'] else ''}"
                             for i, c in enumerate(data_cols, start=2))
            if not dry_run:
                await conn.execute(f"UPDATE {table} SET {sets} WHERE id = $1",
                                   existing, *[_val(spec, row, c) for c in data_cols])
            updated += 1
            continue
        id_free = row.get("id") is not None and not await conn.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM {table} WHERE id = $1)", row["id"])
        cols = (["id"] if id_free else []) + data_cols
        vals = ([row["id"]] if id_free else []) + [_val(spec, row, c) for c in data_cols]
        ph = ", ".join(f"${i}{'::jsonb' if c in spec['jsonb'] else ''}" for i, c in enumerate(cols, start=1))
        if not dry_run:
            await conn.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph})", *vals)
        added += 1
    if not dry_run:
        # id 를 직접 넣었으므로 시퀀스를 최댓값 뒤로 맞춘다
        await conn.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1))")
    print(f"{name}: 추가 {added}, 갱신 {updated}, 건너뜀 {skipped}" + (" (dry-run)" if dry_run else ""))


async def run(replace: bool, dry_run: bool) -> None:
    conn = await asyncpg.connect(settings.system_pg_dsn)
    try:
        async with conn.transaction():
            for name, spec in TABLES.items():
                await import_table(conn, name, spec, replace, dry_run)
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replace", action="store_true", help="이미 있는 항목을 seed 내용으로 덮어씀")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 개수만 출력")
    args = ap.parse_args()
    asyncio.run(run(args.replace, args.dry_run))


if __name__ == "__main__":
    main()
