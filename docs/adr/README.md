# Architecture Decision Records — pgxnl

오늘 논의를 거쳐 확정한 주요 설계 결정 기록입니다. 각 ADR은 배경(Context) →
결정(Decision) → 결과/트레이드오프(Consequences) 순으로 작성되어 있습니다.

| # | 제목 | 상태 |
|---|---|---|
| [0001](0001-postgresql-only-scope.md) | 분석 대상 DB를 PostgreSQL로 한정, 단 확장 인터페이스는 유지 | Accepted |
| [0002](0002-antlr4-sql-parser.md) | SQL 파서로 ANTLR4(PostgreSQL grammar) 채택 | Accepted |
| [0003](0003-dual-knowledge-layer.md) | 스키마 용어집과 비정형 문서 지식 레이어를 분리 | Accepted |
| [0004](0004-hybrid-semantic-cache.md) | 시맨틱 캐시를 pg_trgm + 임베딩 하이브리드로 전환하고 캐시 히트에도 검증 재수행 | Accepted |
| [0005](0005-essential-vs-optional-components.md) | 모든 부가 기능을 "필수 경로 + 보조 Provider"로 분리 | Accepted |
| [0006](0006-validation-layer-before-execution.md) | SQL 실행 전에 코드 전용 검증·거버넌스 계층을 강제 | Accepted |
| [0007](0007-pg-stats-reuse.md) | 컬럼 통계 수집에 PostgreSQL 옵티마이저 통계(pg_stats)를 우선 재사용 | Accepted |
| [0008](0008-mschema-dual-representation.md) | 스키마를 경량 검색용 표현과 M-Schema 전체 표현으로 이중화 | Accepted |
| [0009](0009-rules-as-code-not-prompt.md) | SQL 생성 규칙을 프롬프트 텍스트가 아니라 IR 코드 검증으로 이관 | Accepted (부분 적용) |
