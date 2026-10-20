# ADR-0007: 컬럼 통계 수집에 PostgreSQL 옵티마이저 통계(pg_stats)를 우선 재사용

- **상태**: Accepted
- **날짜**: 2026-08
- **관련**: ADR-0001

## Context

기존 `collect_stats` 도구는 대상 DB에 직접 쿼리해 컬럼별 고유값·분포를 수집하는
것으로 추정됐다(원본 설계 문서에 구현 세부사항은 없었음). 그런데 PostgreSQL은
쿼리 플래닝을 위해 `ANALYZE` 시점에 이미 `n_distinct`, `most_common_vals`,
`most_common_freqs`, `histogram_bounds` 같은 통계를 `pg_stats` 뷰로 제공한다.
별도 배치 잡으로 값 예시를 다시 수집하는 것은 이 기존 자산을 무시하는 셈이다.

다만 `pg_stats`는 한계도 있다: 표본 기반(최대 100개 MCV/히스토그램 구간), 1KB
초과 값 제외, `ANALYZE` 미실행/오래된 테이블에서는 신선도 문제, 고카디널리티
ID/FK 후보 컬럼은 MCV가 비어있는 경우가 많다는 점(값이 대부분 고유해 "최빈값"
개념 자체가 무의미).

## Decision

`StatsAdapter` 인터페이스(ADR-0001에서 다룬 DBMS 확장성 원칙에 따라 인터페이스로
분리)를 두고, PostgreSQL 구현체 `PgStatsAdapter`가 `pg_stats`를 1차로 조회한다.
`most_common_vals`가 없거나(`ANALYZE` 미실행/고카디널리티) 값이 없으면, 기존
직접 샘플링 로직으로 폴백한다.

```
collect_stats(table, column):
    1차: PgStatsAdapter.get_column_stats()  — pg_stats 재사용, 저비용
    2차 (폴백): 직접 샘플링 쿼리 실행       — 1차가 비어있을 때만
```

`pg_stat_user_tables.last_analyze`를 함께 조회해 통계 신선도를 판단하는 것을
권장하며, `ColumnStats.source` 필드로 값의 출처(`optimizer_stats` vs
`direct_sample`)를 항상 구분해 남긴다.

## Consequences

- **장점**: 대부분의 컬럼은 별도 배치 잡 없이 `ANALYZE` 주기에 무임승차해 통계를
  얻는다. 직접 샘플링은 통계가 부실한 소수 컬럼(고카디널리티 텍스트, 신규 테이블)
  에만 필요해져 비용이 줄어든다.
- **트레이드오프**: `pg_stats` 조회 자체에 대상 테이블 읽기 권한이 필요하다.
  `n_distinct`가 음수(테이블 크기 대비 비율을 의미)로 나올 수 있어 이를 해석하는
  로직이 별도로 필요하다. 값 예시가 필요한 상황(FK 후보 컬럼 등)에서는 여전히
  직접 샘플링/`TABLESAMPLE` 기반 검증이 필요할 수 있다.
- **재확장 시**: 다른 DBMS를 다시 지원하게 되면 `OracleStatsAdapter`
  (`ALL_TAB_COL_STATISTICS`) 같은 새 구현체만 추가하면 되고, `collect_stats` 도구
  호출부는 변경할 필요가 없다.
