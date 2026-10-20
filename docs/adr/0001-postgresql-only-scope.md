# ADR-0001: 분석 대상 DB를 PostgreSQL로 한정, 단 확장 인터페이스는 유지

- **상태**: Accepted
- **날짜**: 2026-08

## Context

기존 pgxrsa는 PostgreSQL·Oracle·MySQL·Informix 4개 DBMS를 `BaseConnector` 추상화로
지원하도록 설계되어 있었다. 그러나 실제 우선순위는 PostgreSQL이며, 나머지 DBMS
지원을 유지하는 데 드는 구현·테스트 비용이 현재 필요성 대비 크다는 판단이 있었다.

동시에, 향후 다시 다른 DBMS(특히 Oracle)를 지원해야 할 가능성이 완전히 배제되지는
않는다는 점도 확인됐다.

## Decision

- 분석 대상 DB를 **PostgreSQL로 한정**한다. `PgConnector` 구현체 하나만 실제로
  등록·노출한다.
- 단, `BaseConnector`, `StatsAdapter` 등 DBMS 비의존적이어야 하는 인터페이스는
  **걷어내지 않고 유지**한다. 인터페이스까지 제거하면 향후 재확장 시 처음부터
  다시 설계해야 하기 때문이다.
- `target_connector` 등록 시점에 `dialect != "postgresql"`이면 명시적으로 예외를
  던지는 가드를 코드에 둔다 — "인터페이스는 열려 있지만 지금은 PG만 지원한다"는
  현재 범위를 문서가 아니라 코드 레벨에서 강제한다.

## Consequences

- **장점**: 구현·테스트 범위가 확 줄어든다. Dialect별 SQL 문법 차이를 흡수하는
  로직을 유지보수할 필요가 없다. PostgreSQL 네이티브 기능(pg_stats,
  pg_stat_statements, RLS)을 어댑터 계층 없이 직접 활용할 수 있다 (ADR-0007 참고).
- **트레이드오프**: 인터페이스를 유지하는 만큼 최소한의 추상화 비용(간접 호출,
  범용 데이터 클래스 설계)은 계속 남는다. "지금 안 쓰는 유연성"에 대한 비용이다.
- **재확장 시 해야 할 일**: 새 DBMS의 `BaseConnector`/`StatsAdapter` 구현체 추가,
  ANTLR grammar 추가(ADR-0002), dialect 가드 완화. `agent/orchestrator.py`,
  `agent/canonicalize.py`, `agent/validation.py`는 이 인터페이스들만 사용하므로
  변경이 필요 없어야 한다 — 만약 필요해진다면 인터페이스 설계가 새어나갔다는
  신호로 보고 재검토한다.
