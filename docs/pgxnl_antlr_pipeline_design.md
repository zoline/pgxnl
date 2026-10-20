# pgxnl: ANTLR 기반 SQL 분해/비교 파이프라인 설계 문서

## 0. 배경 및 목표

현재 pgxnl은 Qwen3 계열 모델로 BIRD SQL 벤치마크를 테스트 중이며, gold 대비 약 50% 수준의 정확도를 보이고 있다. 논의를 통해 다음 다섯 가지 근본 이슈가 식별되었다.

1. 모델 크기보다 파이프라인 구조가 병목일 가능성이 높음
2. Glossary가 실데이터 대비 커버리지가 부족함
3. Rule을 프롬프트 텍스트로 누적하면 충돌 및 token 제한 문제 발생
4. BIRD 샘플만으로 RL/DPO 학습 시 범용성이 떨어질 위험
5. 컬럼 개수/순서 차이로 인한 "가짜 오답"이 실제 정확도를 왜곡할 가능성

본 문서는 pgxnl이 이미 보유한 **PostgreSQL 전용 ANTLR4 grammar**를 활용해 위 문제들을 구조적으로 완화하는 파이프라인을 정의한다. 대상 DB는 이미 PostgreSQL로 이관되어 있으므로 dialect 불일치 문제는 없는 상태를 전제로 한다.

---

## 1. 전체 아키텍처

```
[자연어 질문]
      │
      ▼
[LLM: SQL 생성] ──────────────► [생성된 SQL 문자열]
      │                                  │
      │                                  ▼
      │                         [ANTLR4 Parser: PostgreSQL grammar]
      │                                  │
      │                    ┌─────────────┴─────────────┐
      │                    ▼                            ▼
      │             파싱 성공                      파싱 실패
      │                    │                            │
      │                    ▼                            ▼
      │          [Listener/Visitor로            [SyntaxErrorRecord]
      │           절 단위 IR 추출]                 (오답 카테고리: SYNTAX)
      │                    │
      │                    ▼
      │          [정규화된 내부 구조 (Normalized IR)]
      │                    │
      │      ┌─────────────┼─────────────────┐
      │      ▼             ▼                 ▼
      │  [Rule Validator] [Gold IR과 구조 비교] [실행 결과 비교]
      │      │             │                 │
      │      ▼             ▼                 ▼
      │  위반 시 재생성   구조적 근접도       실행 정합성(EX)
      │  요청 (feedback)   지표 산출          최종 판정
      │
      ▼
[오답 발생 시: Perturbation 기반 negative sample 생성 → DPO 학습 데이터로 축적]
```

핵심 설계 원칙:
- **Rule은 프롬프트 텍스트가 아니라 IR에 대한 코드 검증으로 옮긴다** (이슈 3 대응)
- **비교는 실행 결과 + 구조적 IR 비교의 이중 검증으로 한다** (이슈 5 대응)
- **오답은 카테고리화하여 축적하고, 이후 DPO negative sample의 원재료로 재사용한다** (이슈 4 대응, 범용성 확보를 위해 카테고리별 균형을 관리)

---

## 2. ANTLR Listener/Visitor 설계

### 2.1 추출 대상 절(Clause)

| IR 노드 | 대응 SQL 절 | 비고 |
|---|---|---|
| `SelectList` | `SELECT ...` | 컬럼/표현식/alias, 집합으로 취급 |
| `FromClause` | `FROM ...` | 기본 테이블 |
| `JoinClause[]` | `JOIN ...` | 테이블, join 타입, ON 조건 |
| `WherePredicateTree` | `WHERE ...` | AND/OR 트리, leaf는 비교 predicate |
| `GroupByList` | `GROUP BY ...` | 집합으로 취급 |
| `HavingPredicateTree` | `HAVING ...` | WHERE와 동일 구조 재사용 |
| `OrderByList` | `ORDER BY ...` | 순서 유지 (순서 자체가 의미이므로) |
| `LimitOffset` | `LIMIT / OFFSET` | 값 비교 |

### 2.2 Visitor 스켈레톤 (Python + antlr4-python3-runtime 기준)

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SelectItem:
    expr: str          # 정규화된 표현식 (공백/대소문자 정리)
    alias: Optional[str] = None

@dataclass
class PredicateNode:
    op: str                          # 'AND' | 'OR' | 'CMP'
    children: list = field(default_factory=list)   # AND/OR인 경우
    left: Optional[str] = None       # CMP인 경우
    comparator: Optional[str] = None # =, >, <, LIKE, IN 등
    right: Optional[str] = None

@dataclass
class QueryIR:
    select_items: list[SelectItem]
    from_tables: list[str]
    joins: list[dict]                # {table, join_type, on: PredicateNode}
    where: Optional[PredicateNode]
    group_by: list[str]
    having: Optional[PredicateNode]
    order_by: list[tuple[str, str]]  # (expr, ASC/DESC)
    limit: Optional[int]
    offset: Optional[int]


class SQLToIRVisitor(PostgreSQLParserVisitor):
    def visitSelect_statement(self, ctx) -> QueryIR:
        select_items = self._extract_select_list(ctx)
        from_tables, joins = self._extract_from_join(ctx)
        where = self._extract_predicate(ctx.where_clause()) if ctx.where_clause() else None
        group_by = self._extract_group_by(ctx)
        having = self._extract_predicate(ctx.having_clause()) if ctx.having_clause() else None
        order_by = self._extract_order_by(ctx)
        limit, offset = self._extract_limit_offset(ctx)

        return QueryIR(
            select_items=select_items,
            from_tables=from_tables,
            joins=joins,
            where=where,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )

    # _extract_* 메서드들은 각 grammar rule의 ctx를 순회하며
    # 표현식을 문자열로 정규화(공백 제거, 소문자화, alias 분리)한다.
    # WHERE/HAVING은 재귀적으로 AND/OR 트리를 구성한다.
```

### 2.3 에러 처리 (파싱 실패 대응)

```python
from antlr4.error.ErrorListener import ErrorListener

class CollectingErrorListener(ErrorListener):
    def __init__(self):
        self.errors = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append({
            "line": line,
            "column": column,
            "message": msg,
        })

def parse_sql(sql: str) -> tuple[Optional[QueryIR], list[dict]]:
    error_listener = CollectingErrorListener()
    lexer = PostgreSQLLexer(InputStream(sql))
    lexer.removeErrorListeners()
    lexer.addErrorListener(error_listener)

    parser = PostgreSQLParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(error_listener)

    tree = parser.select_statement()

    if error_listener.errors:
        return None, error_listener.errors   # SYNTAX 카테고리로 즉시 분류

    ir = SQLToIRVisitor().visit(tree)
    return ir, []
```

파싱 실패는 **실행조차 하지 않고** 즉시 `SYNTAX` 오답 카테고리로 분류한다. 이 카테고리 비율이 높다면 few-shot 문법 예시 보강이 우선순위가 되고, 낮다면 논리/스키마 이해 쪽에 집중해야 한다는 신호가 된다.

---

## 3. 평가 정규화 로직

### 3.1 이중 비교 전략

```python
def evaluate(pred_sql: str, gold_sql: str, db_conn) -> EvalResult:
    pred_ir, syntax_errors = parse_sql(pred_sql)
    if syntax_errors:
        return EvalResult(correct=False, category="SYNTAX", detail=syntax_errors)

    gold_ir, _ = parse_sql(gold_sql)  # gold는 항상 파싱 성공 가정

    # 1) 구조적 비교 (실행 없이)
    structural_diff = compare_ir(pred_ir, gold_ir)

    # 2) 실행 결과 비교 (기존 EX 메트릭)
    pred_result = execute_normalized(pred_sql, db_conn)
    gold_result = execute_normalized(gold_sql, db_conn)
    exec_match = result_sets_equal(pred_result, gold_result)

    if exec_match:
        return EvalResult(correct=True, category="MATCH")

    # 실행은 불일치하지만 구조적으로 컬럼 집합만 다른 경우 등은
    # 별도 카테고리로 분리하여 "가짜 오답" 여부를 판별
    return EvalResult(
        correct=False,
        category=classify_mismatch(structural_diff),
        detail=structural_diff,
    )
```

### 3.2 구조적 비교 규칙

| 비교 항목 | 방식 |
|---|---|
| SELECT 컬럼 집합 | `set(normalized_expr)` 비교, alias 무시 |
| WHERE predicate | AND 트리는 leaf 집합으로 flatten 후 비교 (OR는 순서 유지) |
| JOIN | (table, join_type, on_predicate) 튜플 집합으로 비교, 순서 무관 |
| GROUP BY | 집합 비교 |
| ORDER BY | 리스트 비교 (순서 유지) — 단, gold에 ORDER BY가 없으면 pred의 순서 차이는 무시 |

### 3.3 실행 결과 정규화 (`execute_normalized`)

- 컬럼 개수가 다르면 gold의 컬럼 이름/개수에 맞춰 pred 결과를 projection
- 행 순서는 gold에 `ORDER BY`가 없는 한 set 비교로 처리
- 타입 캐스팅 정규화 (`1` vs `1.0`, `NULL` 처리 등)

이 단계를 도입한 후 **정규화 전/후 정확도 차이를 반드시 측정**하여, 이슈 5(가짜 오답)가 실제로 몇 %를 차지했는지 정량화한다.

---

## 4. Rule Validator (프롬프트 rule → 코드 검증 전환)

```python
class RuleViolation(Exception):
    def __init__(self, rule_id: str, message: str):
        self.rule_id = rule_id
        self.message = message

def validate_rules(ir: QueryIR, ruleset: list[Rule]) -> list[RuleViolation]:
    violations = []
    for rule in ruleset:
        result = rule.check(ir)   # 각 Rule은 IR을 받아 위반 여부 판정
        if not result.passed:
            violations.append(RuleViolation(rule.id, result.message))
    return violations
```

- Rule은 자연어 프롬프트가 아니라 **IR을 입력받는 함수**로 정의한다 (예: "테이블 A는 항상 컬럼 X로 JOIN해야 한다" → JOIN 노드를 순회하며 검사)
- 위반 시 구체적 위반 내역(어떤 rule, 어떤 노드)을 재생성 프롬프트에 피드백으로 삽입 → 전체 rule 목록을 매번 프롬프트에 넣지 않아도 됨 (token 제한 문제 완화)
- Rule 우선순위/충돌 시 어떤 rule을 우선할지는 `Rule` 객체에 priority 필드를 두어 관리

---

## 5. DPO Negative Sample 생성 (Perturbation)

### 5.1 원칙

- 완전 랜덤 오답이 아니라, **IR의 특정 노드를 의도적으로 변형**하여 "그럴듯한 오답"을 생성
- 변형 지점마다 라벨을 남겨 어떤 연산 단계에서 실수가 났는지 추적 가능하게 함

### 5.2 Perturbation 종류 예시

| 변형 유형 | 방법 | 라벨 |
|---|---|---|
| 컬럼 누락 | SELECT 리스트에서 항목 하나 제거 | `PROJECTION_MISSING` |
| 컬럼 과다 | 관련 없는 컬럼 하나 추가 | `PROJECTION_EXTRA` |
| 조건 반전 | WHERE의 비교연산자를 반대로 (`=`→`!=`, `>`→`<`) | `PREDICATE_INVERTED` |
| JOIN 컬럼 오류 | ON절의 컬럼을 스키마 내 다른 컬럼으로 치환 | `JOIN_COLUMN_WRONG` |
| GROUP BY 누락 | GROUP BY절 제거 | `GROUPBY_MISSING` |
| 집계 함수 오류 | `SUM`→`AVG`, `COUNT`→`COUNT DISTINCT` 등 치환 | `AGG_FUNC_WRONG` |

```python
def generate_negative(gold_ir: QueryIR, perturbation_type: str) -> QueryIR:
    ir_copy = deepcopy(gold_ir)
    perturbation_fn = PERTURBATION_REGISTRY[perturbation_type]
    return perturbation_fn(ir_copy)

def ir_to_sql(ir: QueryIR) -> str:
    # IR → SQL 역변환 (결정론적 규칙)
    ...
```

### 5.3 DPO 페어 축적

```python
@dataclass
class PreferencePair:
    question: str
    positive_sql: str      # gold 또는 실행 검증된 정답
    negative_sql: str
    negative_category: str  # 위 perturbation 라벨 또는 실제 모델이 낸 오답의 SYNTAX/구조 카테고리
    source: str             # "perturbation" | "model_generated"
```

- 실제 모델이 생성한 오답(`source="model_generated"`)과 인위적 perturbation(`source="perturbation"`)을 함께 축적하되, 카테고리별 균형을 맞춰 특정 오류 유형에 과적합되지 않도록 관리
- BIRD 전용 과적합 방지를 위해, 가능하면 pgxnl 자체 스키마/질문셋에서도 동일한 방식으로 페어를 생성해 데이터 소스를 다변화

---

## 6. 오답 카테고리 정의 (통계 산출용)

| 카테고리 | 정의 |
|---|---|
| `SYNTAX` | ANTLR 파싱 자체가 실패 |
| `PROJECTION_MISMATCH` | 실행은 불일치하나 구조 비교상 SELECT 컬럼 집합만 다름 |
| `PREDICATE_MISMATCH` | WHERE/HAVING 조건 구조가 다름 |
| `JOIN_MISMATCH` | JOIN 테이블/조건 구조가 다름 |
| `GROUPBY_MISMATCH` | GROUP BY 구조 차이 |
| `SEMANTIC_WRONG` | 구조도 다르고 실행 결과도 무관 (진짜 논리 오류로 추정) |
| `RULE_VIOLATION` | Rule validator에서 걸린 경우 |

우선 이 카테고리별 분포를 현재 pgxnl 결과셋에 대해 산출하는 것이 다음 단계의 최우선 작업이다. `SYNTAX`와 `PROJECTION_MISMATCH` 비중이 크다면 파이프라인(본 문서의 2~3장) 적용만으로 체감 정확도가 크게 개선될 가능성이 높고, `SEMANTIC_WRONG` 비중이 크다면 스키마 링킹/glossary 개선(이슈 2) 쪽에 우선순위를 둬야 한다.

---

## 7. 구현 순서 제안

1. **1단계**: `SQLToIRVisitor` 구현 (2장) — SELECT/FROM/WHERE 우선, JOIN/GROUP BY는 2차
2. **2단계**: 파싱 성공률 측정 스크립트 — 현재 오답 중 `SYNTAX` 비율 산출 (가장 빠른 진단)
3. **3단계**: `compare_ir` 및 정규화 실행 비교 (3장) 적용 → 정규화 전/후 정확도 비교
4. **4단계**: 오답 카테고리 통계 산출 (6장) → 다음 우선순위 결정
5. **5단계**: Rule validator (4장) 도입 — 기존 프롬프트 rule 중 코드 검증으로 옮길 수 있는 것부터
6. **6단계**: Perturbation 기반 negative sample 축적 (5장) 시작 — DPO는 데이터가 어느 정도 쌓인 이후 별도 프로젝트로 진행

---

## 8. 리스크 및 열린 질문

- ANTLR PostgreSQL grammar가 서브쿼리/CTE(`WITH`)/윈도우 함수까지 커버하는지 확인 필요 — BIRD 문제 중 challenging 난이도는 이런 구문이 많음
- `compare_ir`의 predicate 비교는 논리적으로 동치이나 트리 구조가 다른 경우(예: `A AND B` vs `B AND A`는 잡히지만, De Morgan 법칙 수준의 변형은 못 잡음)를 완전히 해결하지 못함 — 필요시 조건부로 SQL 동치 검증 라이브러리 도입 검토
- Rule 간 우선순위 정책(4장)은 아직 구체적 정책이 없어 실제 rule 목록을 보며 설계 필요
