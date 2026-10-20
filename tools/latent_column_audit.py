"""통과한 문항 중 **컬럼 축이 gold와 다른데 우연히 통과한** 것을 찾는다.

EX는 결과 집합만 비교하므로, 같은 개념을 담은 다른 컬럼을 써도 그 질의의 필터
안에서 두 컬럼이 마침 같은 값이면 통과한다. california_schools는 학교명·교육구명·
카운티명·차터자금유형이 테이블마다 복제돼 있어 이 일이 흔하다.

사용법:
    psql ... -tA -F$'\t' -c "COPY (SELECT seq, ex_pass, pred_sql, gold_sql
        FROM pgxnl_eval_items WHERE run_id=<N> ORDER BY seq) TO STDOUT
        WITH (FORMAT csv, DELIMITER E'\t')" > run.tsv
    python tools/latent_column_audit.py run.tsv

별칭을 해소해 (테이블, 컬럼) 집합으로 비교하고, 차이가 같은 개념 안에서 갈리면
잠재 불일치로 표시한다. 실측(run 301): 통과 28건 중 5건이 여기 걸렸고, 그중
카운티명 1건만 진짜 동치였다(조인 공간 9,986행 전부 일치). 나머지 4건은 필터가
갈리는 행을 비껴갔을 뿐이다.

**추출기는 완벽하지 않다.** gold가 별칭 없이 쓴 컬럼이나 3단 이름(schema.table.column)은
오탐으로 나온다 — 출력의 "컬럼 집합만 다름" 항목은 사람이 확인해야 한다.
"""
import csv, re, sys, collections

ALIAS = re.compile(r'\b(?:FROM|JOIN)\s+([a-zA-Z_"][\w".]*)\s+(?:AS\s+)?([a-zA-Z_]\w*)', re.I)
BARE  = re.compile(r'\b(?:FROM|JOIN)\s+([a-zA-Z_][\w]*)\s*(?=\b(?:WHERE|ON|INNER|LEFT|RIGHT|JOIN|GROUP|ORDER|LIMIT|\)|,|$))', re.I)
REF   = re.compile(r'\b([a-zA-Z_]\w*)\s*\.\s*("(?:[^"]|"")+"|[a-zA-Z_]\w*)')
KW = {'select','from','where','group','order','by','on','and','or','as','inner','left','right','join',
      'count','sum','avg','max','min','cast','real','distinct','having','limit','desc','asc','case',
      'when','then','else','end','not','null','is','in','like','nullif','round','coalesce','substring'}

def qual(sql):
    a2t = {}
    for t, al in ALIAS.findall(sql):
        if al.lower() in KW: continue
        a2t[al.lower()] = t.strip('"').split('.')[-1].lower()
    for t in BARE.findall(sql):
        a2t.setdefault(t.lower(), t.lower())
    out = set()
    for al, col in REF.findall(sql):
        al = al.lower()
        if al in KW: continue
        c = col.strip('"').lower()
        out.add((a2t.get(al, al), c))
    return out, a2t

# 같은 개념인데 테이블마다 이름이 다른 컬럼들
CONCEPT = {}
for name, members in {
  '학교명':      [('schools','school'), ('satscores','sname'), ('frpm','school name')],
  '교육구명':    [('schools','district'), ('satscores','dname'), ('frpm','district name')],
  '카운티명':    [('schools','county'), ('satscores','cname'), ('frpm','county name')],
  '조인키':      [('schools','cdscode'), ('satscores','cds'), ('frpm','cdscode')],
  '차터자금유형':[('schools','fundingtype'), ('frpm','charter funding type')],
  '차터여부':    [('schools','charter'), ('frpm','charter school (y/n)')],
  '차터번호':    [('schools','charternum'), ('frpm','charter school number')],
  '학교유형':    [('schools','soctype'), ('schools','soc'), ('frpm','school type')],
  '교육옵션':    [('schools','edopsname'), ('schools','edopscode'), ('frpm','educational option type')],
  '학년범위':    [('schools','gsoffered'), ('schools','gsserved')],
}.items():
    for m in members: CONCEPT[m] = name

rows = list(csv.reader(open(sys.argv[1]), delimiter='\t'))
print(f"{'seq':>4} {'EX':2}  차이")
print('-'*100)
n_latent = 0
for seq, ex, pred, gold in rows:
    p, pa = qual(pred); g, ga = qual(gold)
    only_p, only_g = p - g, g - p
    if not only_p and not only_g: continue
    # 같은 개념끼리 짝지어지는지
    pc = collections.defaultdict(set); gc = collections.defaultdict(set)
    for x in only_p:
        if x in CONCEPT: pc[CONCEPT[x]].add(x)
    for x in only_g:
        if x in CONCEPT: gc[CONCEPT[x]].add(x)
    swaps = []
    for concept in set(pc) & set(gc):
        for a in pc[concept]:
            for b in gc[concept]:
                swaps.append((concept, a, b))
    if ex == 't' and swaps:
        n_latent += 1
        print(f"{seq:>4} {'통과':2}  ⚠ 잠재 불일치")
        for c, a, b in sorted(swaps):
            print(f"          {c:<12} pred {a[0]}.{a[1]:<24} ← → gold {b[0]}.{b[1]}")
    elif ex == 't':
        rest_p = {x for x in only_p if x not in CONCEPT}
        rest_g = {x for x in only_g if x not in CONCEPT}
        if rest_p or rest_g:
            print(f"{seq:>4} {'통과':2}  컬럼 집합만 다름 (같은 개념 아님)")
            if rest_p: print(f"          pred만: {', '.join(f'{t}.{c}' for t,c in sorted(rest_p))}")
            if rest_g: print(f"          gold만: {', '.join(f'{t}.{c}' for t,c in sorted(rest_g))}")
print('-'*100)
print(f"통과 문항 중 같은 개념 컬럼을 서로 다르게 쓴 건: {n_latent}건")
