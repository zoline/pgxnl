import os
"""ORDER BY + LIMIT 을 쓰는 gold에서 경계값에 동점이 있는지 — 답이 유일한지 검사.

관계형 데이터는 집합이라 순서가 없다. 순서를 요구하는 질문에서 잘라내는 경계에
동점이 걸리면, 동점을 가르는 규칙이 없는 한 **답이 존재하지 않는다**.
"""
import csv, re, sys, asyncio, asyncpg

ORDER_RE = re.compile(r'\sORDER\s+BY\s+(.*?)(?:\s+LIMIT\s+(\d+))(?:\s+OFFSET\s+(\d+))?\s*$', re.I | re.S)
FROM_RE  = re.compile(r'\sFROM\s', re.I)

def build_check(gold: str):
    m = ORDER_RE.search(gold.strip())
    if not m:
        return None
    order_expr, limit, offset = m.group(1).strip(), int(m.group(2)), int(m.group(3) or 0)
    head = gold[:m.start()]
    fm = FROM_RE.search(head)
    if not fm:
        return None
    rest = head[fm.start():]          # FROM ... WHERE ... GROUP BY ...
    need = offset + limit
    return f"""
WITH r AS (SELECT RANK() OVER (ORDER BY {order_expr}) AS rnk {rest}),
     cut AS (SELECT max(rnk) AS b FROM (SELECT rnk FROM r ORDER BY rnk LIMIT {need}) z)
SELECT (SELECT count(*) FROM r WHERE rnk <= (SELECT b FROM cut)) AS covered, {need} AS needed
""", need

async def main(path):
    conn = await asyncpg.connect(os.environ['BIRD_PG_DSN'])  # 예: postgresql://user:pass@host:5432/BIRD
    await conn.execute("SET search_path=california_schools")
    rows = list(csv.reader(open(path), delimiter='\t'))
    checked = skipped = bad = 0
    for seq, ex, gold in rows:
        built = build_check(gold)
        if built is None:
            if re.search(r'\sLIMIT\s', gold, re.I):
                print(f"{seq}  [건너뜀 — 형태를 못 읽음]")
                skipped += 1
            continue
        sql, need = built
        try:
            r = await conn.fetchrow(sql)
        except Exception as exc:
            print(f"{seq}  [검사 실패] {str(exc)[:70]}")
            skipped += 1
            continue
        checked += 1
        covered, needed = r['covered'], r['needed']
        if covered > needed:
            bad += 1
            print(f"{seq}  ⚠ 동점이 경계를 넘음 — {needed}행을 요구하는데 동순위가 {covered}행 "
                  f"({'통과' if ex=='t' else '실패'})")
        else:
            print(f"{seq}  ok  ({needed}행 요구, 동순위 {covered}행)")
    await conn.close()
    print(f"\n검사 {checked}건 / 건너뜀 {skipped}건 / 답이 유일하지 않음 {bad}건")

asyncio.run(main(sys.argv[1]))
