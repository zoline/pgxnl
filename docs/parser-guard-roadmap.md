# ANTLR 파서로 가드를 강화한다 (제안)

2026-09-09 작성. 이 날 가드 세 개(`column_rationale`, `redundant_join`, 그리고 기존
`CanonicalColumnRule` 완화)를 만들며 부딪힌 한계를 모았다. **공통 원인이 하나다: 파싱이
최상위 SELECT 한 겹에서 멈춘다.** 문법 트리는 이미 다 있는데(ANTLR `PostgreSQLParser`)
IR이 그 정보를 버린다.

## 지금 못 하는 것과, 파싱하면 되는 것

### 1. 스코프를 구분하지 못한다

`ParsedStatement.alias_to_table`은 **평면 dict**다. 서브쿼리가 바깥과 같은 별칭을 다른
테이블에 쓰면 안쪽이 바깥을 조용히 덮어쓴다.

```sql
SELECT a.x FROM frpm AS a WHERE a.y > (SELECT max(a.z) FROM schools AS a)
-- alias_to_table = {'a': 'schools'}   바깥 a.x를 schools로 오해한다
```

2026-09-09에 `ambiguous_aliases`(별칭이 두 테이블에 묶였는지)를 노출해 **위험을 감지**만
했다. `CanonicalColumnRule`은 그 경우 손을 뗀다. 근본 해결은 **스코프 트리**다:

- `Select_with_parens`마다 새 스코프를 열고, 각 스코프의 FROM/JOIN에서 별칭을 수집
- 컬럼 참조는 가장 가까운 감싸는 스코프에서 해석
- 재료는 이미 있다 — `ir_builder`의 `_SUBQUERY_CTX` prune 워크가 같은 경계를 쓴다

**효과:** 서브쿼리를 쓴 질의에서도 정본 교정이 동작한다. 지금은 별칭 충돌이 없을 때만
동작하고, 파생 테이블이 있으면 통째로 포기한다.

### 2. 파생 테이블의 컬럼 출처를 모른다

```sql
SELECT x."School Name" FROM (SELECT "School Name" FROM frpm) x JOIN schools AS T2 ON true
```

`x`는 테이블 별칭이 아니라 **서브쿼리의 출력**이다. 파서는 파생 별칭을 "마지막으로 본
테이블"에 묶으므로(`x -> frpm`) 별칭 충돌로는 안 걸린다. 지금은 파생 테이블이 보이면
`CanonicalColumnRule`이 전부 포기한다.

파싱하면: 파생 테이블의 select list를 읽어 `x."School Name"`이 어느 실체 컬럼에서
왔는지 잇는다. 그러면 **서브쿼리 안쪽을 고치는** 교정이 가능해진다 — 지금은 바깥
참조만 볼 수 있어 손댈 수 없다.

### 3. 절(clause) 소속을 텍스트로 추정한다

`redundant_join`은 "이 별칭이 WHERE에 나오는가"를 알아야 하는데, `PredicateNode`를
문자열로 이어붙인 뒤 정규식으로 `별칭.` 패턴을 찾는다. 동작은 하지만 근사치다.

파스 트리를 걸으면 각 `ColumnrefContext`의 **조상 노드**로 절을 정확히 알 수 있다
(SELECT / WHERE / GROUP BY / HAVING / ORDER BY / JOIN ON / 서브쿼리 안). 그러면:

- `redundant_join`의 판정이 정확해진다(지금은 `_predicate_text` 직렬화에 의존)
- 아래 4번이 가능해진다

### 4. REQUESTED vs CONDITION을 LLM에 묻고 있다

`column_rationale` 가드는 "이 SELECT 항목을 질문이 요구했는가"를 **LLM 호출 1회**로
판정한다(질의당 약 2.5초). 정밀도는 gold 56항목 오탐 0으로 좋지만 비용이 든다.

일부는 문법만으로 판정된다. BIRD 456이 그 예다:

```sql
SELECT T1.school, T2."Enrollment (K-12)" ... ORDER BY T2."Enrollment (K-12)" DESC LIMIT 1
--                └─ SELECT에도 ORDER BY에도 나온다. 정렬 기준일 뿐일 가능성이 높다
```

**"SELECT에 있으면서 ORDER BY에만 추가로 쓰이는 컬럼"**은 구문으로 뽑을 수 있다.
LLM 판정을 대체하지는 못하지만(질문 해석이 필요한 경우가 남는다) 싼 1차 필터가 된다.

### 5. RANK와 LIMIT/OFFSET의 동률 차이를 못 본다

BIRD 448에서 실측: `RANK() ... IN (10, 11)`과 `LIMIT 2 OFFSET 9`는 **동률이 있으면
다른 결과**를 낸다. 10위에 동률 2건이 있어 우연히 같은 2행이 나왔지만, "11위만"을
물었다면 RANK는 0행(11위가 없다), LIMIT/OFFSET은 1행이다.

파싱하면 `RANK() OVER(...)` + `WHERE rnk IN (...)` / `rnk <= n` 패턴을 잡아, 정렬
기준 컬럼에 동률이 있는지 통계로 확인하고(이미 `pg_stats` 접근이 있다) 경고할 수 있다.
이 벤치마크에서는 드러나지 않는 **잠재 오류**다.

### 6. 조인 제거를 결정론적으로 못 한다

`redundant_join`은 **조언만** 한다. 조인을 코드가 지우면 안 되기 때문이다 — INNER JOIN은
매칭 없는 행을 걸러내고 1:N이면 행을 늘린다.

파싱 + 카탈로그로 좁히면 안전한 경우를 가릴 수 있다:

- 조인 조건이 **등가**이고, 우변이 대상 테이블의 **PK/UNIQUE**이면 매칭은 최대 1건
- 그러면 조인은 "행을 늘리지 않고, 매칭 없는 행만 거른다"
- 매칭 없는 행이 0건임을 확인하면(카운트 질의 한 번) 제거가 결과를 바꾸지 않는다

여기까지 확인되면 결정론적 제거가 가능하다. **확인 없이 지우면 조용한 오답이다**
(ADR-0009 "모호하면 손대지 않는다").

## 왜 이 방향인가

2026-09-09 하루 측정에서 갈린 결과:

```
프롬프트 변경   여섯 번 모두 무관한 문항 2~3개를 재배치. 순이득 없음
코드 교정       사본 정본화 +2(441·456), 컬럼 근거 가드 +1(448), 둘 다 손실 0
```

프롬프트는 전역에 영향을 주고 통제가 안 된다. 파싱 기반 판정은 **해당 패턴이 실제로
있을 때만** 발동하므로 다른 문항을 건드리지 않는다.

## 착수 순서 제안

1. **스코프 트리** (1·2 해결) — 나머지의 기반이다. 잘못 고치면 조용한 오답이 되므로
   테스트를 두껍게. 현재 `ambiguous_aliases`/파생 테이블 가드가 안전망 역할을 하니
   그것을 유지한 채 안쪽부터 넓힌다.
2. **절 소속 조회** (3 해결) — `ColumnrefContext -> 절` 매핑 하나면 여러 가드가 정확해진다.
3. **동률 경고** (5) — 독립적이고 위험이 낮다.
4. **안전한 조인 제거** (6) — 1·2가 끝난 뒤. PK 확인과 매칭 카운트가 전제다.

4번을 제외하면 모두 **판정만 하고 SQL을 고치지 않는다** — 오늘 확인한 대로 조언형
가드는 부작용이 없었다.

---

## 2026-09-10 진행 — 세 항목 해소, 새 가드 하나

이 문서가 지적한 "파싱이 최상위 SELECT 한 겹에서 멈춘다"를 토큰 인덱스 구간
(`ctx.start.tokenIndex` ~ `ctx.stop.tokenIndex`)으로 푼 것들이다. 스코프 트리를
새로 만들지 않고, `Select_with_parens` 노드의 구간 안/밖만 판정해도 필요한 일은
대부분 됐다.

| 항목 | 구현 | 상태 |
|---|---|---|
| 1. 스코프 구분 | `agent/alias_scope.py`, `CanonicalColumnRule` 스코프 인식 | 해소 |
| 참조 컬럼이 그 테이블에 없음 | `agent/missing_column.py` (스코프 인식) | 신규 |
| 스칼라 서브쿼리 컬럼 개수 | `agent/scalar_subquery.py` | 신규 |

세 가드 모두 **ReAct 루프 안**(`_generate_sql`)에서 되돌린다. 검증 계층은 루프가
끝난 뒤라 모델이 자기 실패를 못 본다 — 실행 오류가 22개 run 내내 같은 형태로
반복된 원인이었다. 루프 안으로 옮긴 뒤 실행 오류가 **0**이 됐다.

### `scalar_subquery` — SELECT 목록의 서브쿼리는 컬럼 하나만

BIRD 465에서 질문이 세 가지를 묻자 모델이 셋을 각각 스칼라 서브쿼리로 만들었고,
그중 하나가 2컬럼이었다 — `subquery must return only one column`으로 죽는다.

조상을 거슬러 `Target_el`을 `Table_ref`보다 먼저 만나는 경우만 스칼라 위치로 본다.
FROM 서브쿼리·`IN`·`EXISTS`·중첩 서브쿼리는 건드리지 않는다(테스트 11건).

**컬럼 근거 검사(`column_rationale`)는 이걸 못 잡는다.** 세 컬럼 모두 질문 구절에
대응해 `[REQUESTED] ✓` 를 받는다 — 그쪽 축은 "질문에 근거가 있나"고 이쪽은
"실행되나"다. 축이 다르면 서로를 대신할 수 없다.

### 도중에 드러난 것

`TokenEdit(kind="delete")` 가 동작하지 않았다 — `postgresql_parser.rewrite()` 가
`deleteRange()` 를 부르는데 antlr4 파이썬 런타임에는 그 이름이 없다(자바 쪽
이름이다). `delete` 를 쓴 규칙이 하나도 없어 드러나지 않았다. 이 문서가 제안하는
가드 중 텍스트를 **지우는** 것을 만들려면 이 경로를 쓰게 되므로 기록해 둔다.
`replaceRange(..., "")` 로 고쳤다.
