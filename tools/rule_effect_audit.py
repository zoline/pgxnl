"""규칙이 **겨냥한 행동**에 기여하는지 센다 — EX보다 먼저 볼 숫자.

EX로는 규칙의 값어치를 판정할 수 없다. 프롬프트를 한 글자 바꾸면(넣든 빼든) 같은
문항 3~4건이 같은 방식으로 깨진다 — 편집 내용이 아니라 프롬프트가 바뀐 사실이 원인이고,
파이프라인이 결정론적이라 반복해도 평균되지 않는다(2026-09-11 실측: 규칙 22를 끄자
EX가 4 떨어졌지만 컬럼 순서 위반은 1건에서 1건으로 변화 없음).

그래서 판정은 이렇게 한다:

    ① 규칙을 끈 run과 켠 run에서 **그 규칙이 겨냥한 위반**을 각각 센다
    ② 변화가 없으면 그 규칙은 기여가 0이다 (다른 무언가가 이미 그 일을 한다)
    ③ 제거는 평가 세트가 커질 때 한다 — 30문항에서는 제거 자체가 -4를 만든다

**두 run은 감사하려는 규칙만 달라야 한다.** 다른 규칙이 켜진 채인 쌍을 넣으면 그 규칙의
칸은 판정이 아니라 "위반이 몇 건이었나"일 뿐이다. 실측(308 vs 310, 규칙 22만 끈 쌍):
규칙 13은 **양쪽 다 켜져 있었는데** 310에서 위반 2건이 나왔다 — 규칙 22를 뺀 교란이
규칙 13의 준수까지 무너뜨렸다. 프롬프트 민감도는 규칙 사이로도 번진다.

사용법:
    python tools/rule_effect_audit.py <켠 run id> <끈 run id>
"""
from __future__ import annotations

import asyncio
import re
import sys

TYPES = {'real', 'integer', 'int', 'text', 'numeric', 'decimal', 'date', 'timestamp',
         'bigint', 'float', 'varchar', 'char', 'boolean'}

# 규칙 21 — SQLite/다른 방언 관용구. BIRD gold가 SQLite 원본이라 흐를 여지가 있다.
DIALECT = {
    '백틱': r'`', 'IFNULL(': r'\bIFNULL\s*\(', 'strftime(': r'\bstrftime\s*\(',
    'datetime(': r'\bdatetime\s*\(', 'LIMIT a,b': r'\bLIMIT\s+\d+\s*,\s*\d+',
    'SELECT TOP': r'\bSELECT\s+TOP\s+\d+', 'ISNULL(': r'\bISNULL\s*\(',
    'GETDATE()': r'\bGETDATE\s*\(', 'julianday(': r'\bjulianday\s*\(',
    'group_concat(': r'\bgroup_concat\s*\(', 'IIF(': r'\bIIF\s*\(',
    '이중따옴표 문자열': r'=\s*"[^"]*"',
}


def _norm(sql: str) -> str:
    """개행·연속 공백을 단일 공백으로. 검사들이 `' FROM '` 처럼 공백을 두른 패턴을 쓰므로
    정규화가 없으면 DB에서 읽은 여러 줄 SQL에서 조용히 빗나간다 — 실측으로 규칙 12가
    SELECT 목록 대신 SQL 전체를 훑어 `FROM schema.table AS T1` 을 컬럼 별칭으로 셌다."""
    return ' '.join((sql or '').split())


def _mask(sql: str) -> str:
    """따옴표 안의 내용을 같은 길이의 밑줄로 가린다 — 식별자·리터럴 안의 기호를 문법으로
    오독하지 않기 위함이다. 실측: `"Charter School (Y/N)"` 의 슬래시를 나눗셈으로 세서
    규칙 4 위반이 없는 SQL을 위반으로 판정했다. 길이를 유지해 위치 기반 문맥 출력이
    어긋나지 않게 한다."""
    out, i, n = [], 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in '"\'':
            j = sql.find(ch, i + 1)
            if j < 0:
                out.append('_' * (n - i)); break
            out.append(ch + '_' * (j - i - 1) + ch); i = j + 1
        else:
            out.append(ch); i += 1
    return ''.join(out)


def rule4(sql: str) -> list[str]:
    """나눗셈 분모가 컬럼인데 NULLIF가 없으면 위반. 리터럴 분모(/ 12)는 0이 될 수 없다."""
    sql = _norm(sql)
    scan = _mask(sql)          # 따옴표 안의 '/' 는 나눗셈이 아니다
    out = []
    for m in re.finditer(r'/\s*([^\s,)]+)', scan):
        d = m.group(1)
        if re.fullmatch(r'-?\d+(\.\d+)?', d) or d.upper().startswith('NULLIF'):
            continue
        out.append(sql[max(0, m.start() - 50):m.start() + 50].strip())
    return out


def rule12(sql: str) -> list[tuple[str, str]]:
    """단순 컬럼 참조에 불필요한 AS 별칭. CAST(... AS 타입)은 제외."""
    sql = _norm(sql)
    up = sql.upper()
    head = sql[:up.find(' FROM ')] if ' FROM ' in up else sql
    out = []
    for m in re.finditer(r'\b(\w+\.(?:"[^"]+"|\w+))\s+AS\s+(\w+)', head, re.I):
        if m.group(2).lower() in TYPES:
            continue
        if head[:m.start()].upper().rstrip().endswith('CAST('):
            continue
        out.append((m.group(1), m.group(2)))
    return out


def rule13(sql: str) -> list[str] | None:
    """테이블 별칭이 T1, T2, T3 … 순인가."""
    al = re.findall(r'\b(?:FROM|JOIN)\s+(?:[\w".]+)\s+AS\s+([A-Za-z]\w*)', _norm(sql), re.I)
    return al if al and al != [f"T{i + 1}" for i in range(len(al))] else None


def rule21(sql: str) -> list[str]:
    return [name for name, pat in DIALECT.items() if re.search(pat, _norm(sql), re.I)]


def rule22(question: str, sql: str) -> list[str] | None:
    """SELECT 컬럼이 질문에 언급된 순서인가. 질문에 이름이 나오는 컬럼만 본다."""
    sql = _norm(sql)
    up = sql.upper()
    i, j = up.find('SELECT') + 6, up.find(' FROM ')
    if j < 0:
        return None
    items, depth, cur = [], 0, ''
    for ch in sql[i:j]:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            items.append(cur.strip()); cur = ''
        else:
            cur += ch
    if cur.strip():
        items.append(cur.strip())
    ql, pos = question.lower(), []
    for c in items:
        c = re.sub(r'\s+AS\s+\w+$', '', c, flags=re.I)
        m = re.findall(r'"([^"]+)"|(\w+)\.(\w+)|^(\w+)$', c)
        if not m:
            continue
        a = m[-1]
        n = (a[0] or a[2] or a[3] or '').lower()
        if not n:
            continue
        k = ql.find(n)
        if k >= 0:
            pos.append((n, k))
    if len(pos) >= 2 and [p for _, p in pos] != sorted(p for _, p in pos):
        return [n for n, _ in pos]
    return None


CHECKS = {
    '규칙 4  나눗셈 CAST/NULLIF': lambda q, s: rule4(s),
    '규칙 12 불필요한 AS 별칭':   lambda q, s: rule12(s),
    '규칙 13 별칭 T1..Tn 순서':   lambda q, s: rule13(s),
    '규칙 21 비-PostgreSQL 관용구': lambda q, s: rule21(s),
    '규칙 22 컬럼 순서':          rule22,
}


async def main(run_on: int, run_off: int) -> None:
    import asyncpg
    from pgxnl.settings import settings
    conn = await asyncpg.connect(settings.system_pg_dsn)
    result: dict[str, dict[int, list[str]]] = {k: {} for k in CHECKS}
    for run in (run_on, run_off):
        rows = await conn.fetch(
            "SELECT seq, question, pred_sql FROM pgxnl_eval_items "
            "WHERE run_id = $1 AND pred_sql IS NOT NULL ORDER BY seq", run)
        for name, fn in CHECKS.items():
            hits = [str(r['seq']) for r in rows if fn(r['question'] or '', r['pred_sql'])]
            result[name][run] = hits
    await conn.close()

    print(f"{'검사':<28} {f'run {run_on} (켬)':<16} {f'run {run_off} (끔)':<16} 판정")
    print('-' * 86)
    for name, per in result.items():
        on, off = per[run_on], per[run_off]
        verdict = '기여 없음' if len(on) == len(off) else f'기여 있음 ({len(off) - len(on):+d}건)'
        print(f"{name:<28} {str(len(on)) + '건':<16} {str(len(off)) + '건':<16} {verdict}")
        if off and len(off) != len(on):
            print(f"{'':28} 끈 run의 위반 문항: {', '.join(off[:8])}")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    asyncio.run(main(int(sys.argv[1]), int(sys.argv[2])))
