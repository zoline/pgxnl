# ADR-0009: SQL 생성 규칙을 프롬프트 텍스트가 아니라 IR 코드 검증으로 옮긴다

- **상태**: Accepted (적용 2건 — NULL 정렬, 중복 컬럼 제거)
- **날짜**: 2026-09

## Context

SQL 생성 규칙(`pgxnl_rules`의 `generation_constraint`)은 지금까지 자연어 텍스트로
시스템 프롬프트에 실려 왔다. 이 방식에는 세 가지 문제가 누적됐다.

1. **규칙이 지켜지지 않는다.** 규칙 수가 늘수록 모델이 일부를 무시한다.
2. **규칙끼리 충돌한다.** 문구를 다듬으면 한 문항은 좋아지고 다른 문항이 깨진다
   (규칙 9번 FK 과적합, DISTINCT 포괄 규칙 사례 — 둘 다 30문항 전체로는 순감소였다).
3. **토큰 압박.** 스키마 컨텍스트가 이미 긴데 규칙까지 앞쪽에 배치해야 잘 지켜진다.

2026-09-02에 이를 정량화할 근거가 나왔다. `pgxnl_rules` id=1은 BIRD 대상으로
**이미 활성화된 프롬프트 규칙**이었다:

> "ORDER BY 컬럼에 NULL이 포함되는 경우, ASC인 경우 NULLS FIRST, DESC인 경우
> NULLS LAST를 추가해 주세요."

그런데 run 93/94에서 **오답 17건 중 8건(47%)이 정확히 이 규칙 위반**이었다.
규칙이 프롬프트에 있는데도 절반 가까이 무시된 것이다.

배경: PostgreSQL은 `ASC→NULLS LAST` / `DESC→NULLS FIRST`인데 SQLite는 정반대다.
BIRD gold는 SQLite 원본을 PG로 옮기며 명시적 NULLS 절로 이를 보존했고, 모델이 그냥
`DESC`만 쓰면 NULL 행이 1위로 올라와 top-N 질의가 통째로 틀린다. seq 459는
`NULLS LAST` 하나 차이로 오답이었다.

## Decision

**결정론적으로 판정 가능한 규칙은 프롬프트에서 코드로 옮긴다.** 판정 대상은 자연어가
아니라 파스 트리에서 뽑은 절 단위 IR(`pgxnl/parsing/ir.py`의 `QueryIR`)이다.

- 적용 지점은 기존 Canonicalization 기구(`agent/canonicalize.py`의 `CanonRule` +
  `TokenEdit` + `TokenStreamRewriter`)를 그대로 쓴다. 새 기구를 만들지 않는다.
- 규칙 정의는 계속 `pgxnl_rules`에 두되, `rule_type='canonicalization'`으로 등록하고
  `definition.kind`로 구현 클래스를 고른다(`load_rules_from_store()`).
- 첫 적용 대상은 NULL 정렬(`OrderByNullsRule`)이다. 모드를 둘로 나눈다:
  - `desc_last`(기본) — `DESC`에만 `NULLS LAST`. `ORDER BY score DESC LIMIT 1`이 NULL
    행을 집어오는 건 벤치마크와 무관하게 거의 항상 버그이므로 일반 업무 DB에도 안전하다.
  - `sqlite` — `ASC→NULLS FIRST`, `DESC→NULLS LAST`. BIRD gold와 일치하지만
    **벤치마크 전용**이다. PostgreSQL 네이티브 의미를 기대하는 고객 DB에는 켜지 않는다.
- 이미 명시된 NULLS 절은 덮어쓰지 않는다 — 모델이 의도한 의미를 파괴하지 않기 위함.

**모든 규칙을 옮기지는 않는다.** 코드로 옮길 수 있는 것은 문법·구조만 보고 판정 가능한
규칙이다. 도메인 지식이 필요한 것(어느 테이블의 컬럼이 이 질문에 맞는지 등)은 규칙이
아니라 glossary의 몫이다.

## Consequences

**확인된 효과**: run 100에서 pred의 NULLS 절 포함이 3/30 → 11/30으로 늘고, **오답 중
NULLS 누락이 8/17 → 0/19로 완전히 사라졌다.** 규칙 준수율이 문제였다는 진단이 맞았다.

### `ASC NULLS FIRST`는 넣지 않는다 (검증 완료)

`mode='sqlite'`의 나머지 절반(`ASC → NULLS FIRST`)을 실제로 적용해 측정한 결과,
**얻은 문항 0개 / 잃은 문항 1개**였다. gold에 `ASC NULLS FIRST`가 있는 문항은 2건뿐인데
성격이 정반대다:

**27B에서 반복 실측한 결과(2026-09-02, 인프라 실패 run 제외)**:

| 모드 | EX | 평균 | σ |
|---|---|---|---|
| `desc_last` | 20, 20, 20 | **20.0/30 = 66.7%** | **0.00** |
| `sqlite` (ASC NULLS FIRST 포함) | 20, 19 | 19.5/30 = 65.0% | 0.50 |

문항 단위로는 450·453이 갈리지만 **1대1 교환이 아니다** — 두 경우 모두 `ASC NULLS FIRST`가
의미적으로 더 나쁜 SQL을 만들고, 450에서만 그 나쁜 SQL이 gold와 우연히 일치한다.

```
seq 450   desc_last = XXX      sqlite = OO
seq 453   desc_last = OOO      sqlite = XX
```

**seq 453 실측** (Fresno Unified 16행 중 `avgscrread` NULL 5행):

| SQL | 결과 |
|---|---|
| gold: `WHERE NOT avgscrread IS NULL ... ORDER BY avgscrread ASC NULLS FIRST LIMIT 1` | phone=(559) 248-5100, score=**370** |
| pred `desc_last`: `ORDER BY avgscrread ASC LIMIT 1` (필터 없음, PG 기본) | phone=(559) 248-5100, score=**370** ✅ |
| pred `sqlite`: `ORDER BY avgscrread ASC NULLS FIRST LIMIT 1` | phone=(559) 490-4290, score=**NULL** ❌ |

`LIMIT 1`에서는 **`NOT x IS NULL` + `ASC NULLS FIRST`** 와 **PostgreSQL 기본 `ASC`(NULLS
LAST)** 가 논리적으로 동치다("NULL 아닌 값 중 최소"). 즉 pred는 운으로 맞은 게 아니라
gold를 간결하게 쓴 것이다. **`sqlite` 규칙은 gold 패턴의 절반(NULLS FIRST)만 적용하고 그
짝인 NULL 필터를 빠뜨려, 멀쩡한 질의를 망가뜨린다** — "가장 낮은 평균 점수 학교"를 물었는데
점수가 아예 없는 학교를 반환한다.

450에서 `sqlite`가 정답이 되는 것도 같은 메커니즘(NULL 행을 "최저"로 반환)이며, gold 450이
그것을 정답으로 정해놨을 뿐이다. **EX가 20.0 vs 19.5로 비슷해 보이는 것은 gold 450의 결함이
만든 착시이고, 정확성 기준으로는 `desc_last`가 명백히 옳다.**

> **측정 사고 주의**: 초판에는 `sqlite`가 `17.3/30(σ=3.09)`으로 **2.4문항 손해**라고
> 적었으나, 그 평균에 **인프라 실패로 9문항이 조용히 실패한 run 113**이 포함돼 있었다.
> 제외하면 차이는 0.5문항이다. `error = str(exc)`가 메시지 없는 예외(TimeoutError 등)를
> 빈 문자열로 만들어 "에러 없이 SQL만 안 나온" 것처럼 보이게 한 것이 원인이며,
> `bird.py`에서 예외 종류를 항상 기록하도록 수정했다.
>
> **교훈**: run 간 차이를 "LLM 비결정성"으로 설명하기 전에 **조용한 실패부터 확인할 것.**
> `temperature=0` + thinking OFF에서 27B는 실제로 결정론적이다(desc_last 3회가 정확히
> 20, 20, 20).

30문항 중 gold가 `ASC NULLS FIRST`를 쓰는 것은 450·453 두 건뿐인데, **성격이 정반대라
규칙으로 둘을 동시에 만족시킬 수 없다.**

| 문항 | gold NULL 필터 | pred NULL 필터 | 규칙 없을 때 | `ASC NULLS FIRST` 추가 시 |
|---|---|---|---|---|
| 450 | 없음 | 없음 | ❌ | **✅ 정답이 됨** |
| 453 | **있음**(`WHERE NOT AvgScrRead IS NULL`) | 없음 | ✅ | **❌ 오답이 됨** |

453의 gold는 WHERE에서 NULL을 먼저 제거하므로 `ASC NULLS FIRST`가 무해하다. 그런데
모델은 그 필터를 쓰지 않으므로, 정렬 절만 흉내 내면 NULL 행이 1위로 올라온다. 반대로
PostgreSQL 기본(`ASC → NULLS LAST`)은 NULL을 뒤로 밀어 **우연히 gold의 필터링된 결과와
일치**한다.

**근본 원인은 gold의 비일관성이다.** 같은 "lowest ~" 질문인데 450은 NULL을 최저값으로
취급해 NULL 행을 답으로 내고, 453은 NULL을 제외한다. 두 pred는 구문상 구별할 수 없으므로
어떤 결정론적 규칙도 둘을 갈라낼 수 없다.

> 주의: 35B로 측정했을 때는 "450은 컬럼 순서(`Street, City, State, Zip` vs
> `street, city, zip, state`)까지 달라 어차피 실패한다"고 기록했으나, **27B는 컬럼 순서를
> 맞추므로 그 근거는 더 이상 유효하지 않다.** 그럼에도 결론은 같다 — 1건 얻고 1건 잃는다.

**결론**: `desc_last`를 유지한다. 이득이 0이면서 PostgreSQL 네이티브 의미와 어긋나는 쪽을
택할 이유가 없다. 실제 고객 DB에서는 `ASC NULLS FIRST` 강제가 명백히 해롭다.

**주의**: 같은 run에서 EX는 오히려 13/30 → 11/30으로 내려갔다. thinking을 함께 켠 것이
원인으로 보이며(서브쿼리·집합연산 오답이 1건 → 5건), 규칙 자체의 기여분은 변수 하나만
바꾼 run 101과의 비교로 별도 확정한다. **"규칙이 지켜지게 만드는 것"과 "EX가 오르는 것"은
다른 문제다** — 이 ADR은 전자만 해결한다.

**한계**: 코드 규칙은 생성 이후에 적용되는 사후 재작성이다. 모델이 애초에 잘못된 컬럼을
고른 것 같은 선택은 되돌릴 수 없다. 그런 유형은 glossary·few-shot의 영역이다.

**따라야 할 것**: 새 규칙을 프롬프트에 추가하려 할 때, 먼저 *"이게 파스 트리만 보고
판정 가능한가"* 를 물을 것. 가능하면 `CanonRule`로 만들고, 불가능하면 그때 프롬프트에
넣되 30문항 전체로 전후 비교할 것(단일 문항 기준 조정 금지 — 규칙 9번 사례).

**규칙 검증에 EX를 쓰지 말 것**: n=30에서 30문항 중 12문항이 run마다 뒤집히므로
±1~2 차이는 노이즈다. 규칙이 작동했는지는 **해당 에러 유형의 건수**로 판정한다
(NULLS 누락 8→0, `column does not exist` 3→0처럼). EX는 "그 오류를 고쳐도 다른 이유로
여전히 틀리는" 문항 때문에 움직이지 않을 수 있고, 그것은 규칙의 실패가 아니다.

**프롬프트 규칙의 두 번째 실패 양상**: 규칙이 *지켜지지 않는* 것(NULLS 사례)뿐 아니라
*잘못된 방향으로 지켜지는* 경우도 있다. 규칙 id=7은 순위 질문에 `RANK() OVER` 사용을
지시하는데, 실측상 순위성 질문 13건 중 gold가 RANK를 쓰는 건 2건이고 **9건은
`ORDER BY ... LIMIT`** 이다. 이 규칙이 모델을 RANK로 밀어 `window functions are not
allowed in WHERE` 에러를 만들고 있다(run 105에서 2건). 규칙을 추가할 때는 **gold가
실제로 어떤 형태를 쓰는지 먼저 세어볼 것.**

## 2026-09-10 추가: 두 번째 적용과 새 분류

### 두 번째 적용 — `dedupe_columns`

BIRD 465에서 모델이 같은 집계식을 두 컬럼으로 냈다(`COUNT(*) AS count, T1.city,
COUNT(*) AS city_count`). 파스 트리에서 별칭을 뗀 식으로 동일성을 판정해 마지막
하나만 남긴다(`DedupeColumnsRule`).

**같은 지식을 앞과 뒤에 각각 두고 재봤다** — 이 ADR의 결정을 처음으로 대조 실험한
사례다.

| | EX | 결과 |
|---|---|---|
| 기준선 (run 301) | 28 | 실패 446·465 |
| few_shot으로 **프롬프트 앞** (run 302) | **26** | 465 얻고 444·447·452 잃음 |
| `dedupe_columns`로 **코드, 뒤** (run 304) | **29** | 465 얻고 손실 0 |

302에서 깨진 셋은 few-shot 내용과 논리적 관계가 없다(444는 규칙 4의 CAST/NULLIF가
사라지고 `LIKE 'Riverside%'`의 와일드카드까지 빠졌다, 452는 county→city, 447은
자금유형 컬럼 반전). **내용 충돌이 아니라 텍스트가 늘어서 흔들렸다.**

교훈: 예외를 프롬프트 앞에 두면 30문항 전부에서 저울질이 일어나고 1문항에서만
쓰인다. 비용은 항상, 이득은 가끔이다.

### 새 분류 `canonical_rewrite`

이 ADR은 "판정 가능한 것은 코드로"라고 했지만, 적용을 막는 실무적 장벽이 하나 있다 —
`canonicalization`은 하나 늘릴 때마다 `CanonRule` 서브클래스와 팩토리 분기를 써야
한다. 그래서 **파서로는 못 정하는데 SQL만 보면 사람은 아는** 변환은 갈 곳이 없었고,
결국 프롬프트로 갔다.

자리는 같고 판정 주체만 LLM인 분류를 만들어 그 구멍을 메운다. 예시 쌍
(`bad_sql` → `good_sql`)을 행 추가만으로 등록한다.

```
rule → few_shot → [SQL 생성] → canonical_rewrite (LLM) → canonicalization (파서)
```

파서가 마지막이다. 뒤집으면 코드가 맞춘 형태를 LLM이 도로 흐트러뜨린다.

**파서로 판정되면 이쪽을 쓰지 않는다.** 확실한 것을 불확실하게 만들 이유가 없다.
LLM 재작성은 경계가 없으므로 코드가 검증하고 어긋나면 원본을 쓴다 — 참조 테이블
집합과 WHERE/HAVING/조인 조건의 리터럴 **순서열**이 같아야 한다(집합으로 비교하면
`city='A' AND county='B'` → `city='B' AND county='A'` 가 통과해 의미가 뒤집힌다).

## 관련

- `docs/pgxnl_antlr_pipeline_design.md` §4 (Rule Validator 설계)
- `docs/pgxnl_accuracy_backlog.md` (측정 기반 우선순위)
- `docs/eval-history.md` (run 94 / 100 / 101)
- ADR-0002 (ANTLR4 파서 채택) — 이 결정의 전제
