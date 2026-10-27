"""시스템 DB의 기준 정보(규칙·용어집·JOIN 그래프·gold 결함)를 seed/*.json 으로 내보낸다.

    python tools/seed_export.py                 # 전역 + BIRD
    python tools/seed_export.py --target BIRD --target mydb

DSN 은 .env 의 PGXNL_SYSTEM_PG_DSN. jsonb 는 ::text 로 받아 json.loads 한다(이중 인코딩 방지).
"""
from __future__ import annotations

import argparse
import asyncio
import json

import asyncpg

from pgxnl.settings import settings
from seed_common import DEFAULT_TARGETS, SEED_DIR, TABLES


async def export(targets: list[str]) -> None:
    conn = await asyncpg.connect(settings.system_pg_dsn)
    try:
        SEED_DIR.mkdir(exist_ok=True)
        for name, spec in TABLES.items():
            cols = ", ".join(f"{c}::text AS {c}" if c in spec["jsonb"] else c for c in spec["columns"])
            where = "target_name = ANY($1::text[])"
            if spec["nullable_target"]:
                where = f"(target_name IS NULL OR {where})"
            rows = await conn.fetch(f"SELECT {cols} FROM {spec['table']} WHERE {where} ORDER BY id", targets)
            out = []
            for r in rows:
                d = dict(r)
                for c in spec["jsonb"]:
                    d[c] = json.loads(d[c])
                out.append(d)
            path = SEED_DIR / f"{name}.json"
            path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(f"{path.relative_to(SEED_DIR.parent)}: {len(out)}")
    finally:
        await conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", action="append", help="내보낼 대상 이름(여러 번 가능). 기본: BIRD, northwind")
    args = ap.parse_args()
    asyncio.run(export(args.target or list(DEFAULT_TARGETS)))


if __name__ == "__main__":
    main()
