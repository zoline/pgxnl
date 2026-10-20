# ADR-0002: SQL 파서로 ANTLR4(PostgreSQL grammar) 채택

- **상태**: Accepted
- **날짜**: 2026-08
- **관련**: ADR-0001

## Context

SQL Canonicalization(§5.8), 검증 계층(§5.9), 실행이력 기반 FK 발견(§5.3)이 모두
SQL을 파싱해야 한다. 두 가지 후보를 검토했다.

| | ANTLR4 (PostgreSQL grammar) | pg_query (libpg_query 바인딩) |
|---|---|---|
| 정확도 | grammar 유지보수 필요, 실제 PG 파서와 미세한 차이 가능성 | PostgreSQL 소스 코드 기반이라 정확도 높음 |
| 확장성 | grammar 교체만으로 타 DBMS 지원 가능 | PostgreSQL 전용, 확장 불가 |
| 의존성 | 순수 생성 코드, C 바인딩 불필요 | libpg_query C 바인딩 필요 |
| SQL 재생성(deparse) | 내장 기능 없음 — TokenStreamRewriter 또는 Visitor로 직접 구현 | 내장 `deparse()` 제공 |

ADR-0001에서 향후 다른 DBMS 재지원 가능성을 열어두기로 했으므로, 파서 선택도 같은
방향과 일관되어야 한다.

## Decision

**ANTLR4 (PostgreSQL grammar)**를 표준 SQL 파서로 채택한다. `pgxnl/parsing/base.py`에
DBMS 비의존적인 `SqlParser` 인터페이스를 두고, `pgxnl/parsing/postgresql_parser.py`가
현재 유일한 구현체다.

SQL 재생성이 필요한 경우(Canonicalization) 두 가지 방식을 규칙의 성격에 따라 나눠
쓴다.

- **TokenStreamRewriter (국소 patch)**: 원본 토큰 스트림은 유지하고 바뀌는 부분만
  삽입/치환/삭제. LIMIT 삽입, ORDER BY 재배치처럼 국소적인 규칙에 적합하며 구현
  비용이 낮다. **초기 규칙 셋은 이 방식으로 시작한다.**
- **Visitor/Listener 전체 재구성**: AST를 순회하며 SQL을 처음부터 재조립. SELECT
  절 컬럼 재배열, 서브쿼리 삽입처럼 구조 자체를 바꿔야 하는 경우에 쓴다. 구현
  비용이 높다(사실상 자체 deparser 구현).

## Consequences

- **장점**: grammar 교체만으로 확장되는 구조이므로 ADR-0001의 결정과 일관된다.
  C 바인딩이 없어 배포·CI 환경 구성이 단순하다.
- **트레이드오프**: pg_query 대비 파싱 정확도를 자체적으로 검증해야 한다 —
  PostgreSQL 자체 문법 변경(신규 버전)이 있을 때 grammar를 갱신해야 하는 유지보수
  부담이 있다. deparse가 내장되어 있지 않아 TokenStreamRewriter/Visitor 구현
  비용이 pg_query 대비 추가로 든다.
- **완화책**: 커뮤니티에서 유지보수되는 grammar(`antlr/grammars-v4`의
  `sql/postgresql`)를 기반으로 시작해 자체 유지보수 부담을 줄인다
  (`pgxnl/grammar/README.md` 참고).
