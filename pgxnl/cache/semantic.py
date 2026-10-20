"""하이브리드 시맨틱 캐시. design 문서 §5.12 / ADR-0004 참고.

1차: pg_trgm 어휘 유사도로 저비용 스크리닝.
2차(옵션): 임베딩 코사인 유사도로 의미 기반 재조회 — Schema RAG와 동일한 임베딩을 재사용.

중요: 캐시 히트는 SQL "생성" 단계만 건너뛴다. 권한 검사(§5.9 검증 계층)는 캐시
히트 여부와 무관하게 항상 재수행되어야 한다 — 이 책임은 Orchestrator(§5.1)에 있으며
이 모듈은 캐시 조회/저장만 담당한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import asyncpg

from pgxnl.llm.embeddings import EmbedFn


@dataclass
class CacheEntry:
    question: str
    answer: str
    sql_steps: list[dict[str, Any]]
    hit_count: int


class SemanticCache:
    def __init__(
        self,
        pool: asyncpg.Pool,
        embed_fn: EmbedFn | None,
        *,
        trgm_threshold: float = 0.85,
        embedding_threshold: float = 0.90,
        embedding_enabled: bool = False,
        ttl_seconds: int = 86_400,
    ) -> None:
        self._pool = pool
        self._embed_fn = embed_fn
        self._trgm_threshold = trgm_threshold
        self._embedding_threshold = embedding_threshold
        self._embedding_enabled = embedding_enabled and embed_fn is not None
        self._ttl = ttl_seconds

    async def lookup(self, question: str, target_db: str, schema: str = "public") -> CacheEntry | None:
        """schema: 같은 target_db 안에서도 스키마가 다르면 같은 질문이 다른 정답으로
        이어질 수 있어(예: BIRD처럼 db_id별 스키마가 갈리는 경우) 캐시 키에 포함한다
        — 빠뜨리면 스키마를 넘나들며 엉뚱한 캐시가 히트한다(실측으로 확인, §5.4 근처
        참고)."""
        row = await self._pool.fetchrow(
            """
            SELECT question, answer, sql_steps, hit_count
            FROM pgxnl_cache
            WHERE target_db = $1 AND schema_name = $2
              AND similarity(question, $3) >= $4
              AND created_at > now() - ($5 * interval '1 second')
            ORDER BY similarity(question, $3) DESC
            LIMIT 1
            """,
            target_db,
            schema,
            question,
            self._trgm_threshold,
            self._ttl,
        )
        if row is not None:
            await self._bump_hit_count(target_db, schema, row["question"])
            return CacheEntry(row["question"], row["answer"], row["sql_steps"], row["hit_count"] + 1)

        if not self._embedding_enabled:
            return None

        qvec = await self._embed_fn(question)
        row = await self._pool.fetchrow(
            """
            SELECT question, answer, sql_steps, hit_count,
                   1 - (embedding <=> CAST($1 AS vector)) AS score
            FROM pgxnl_cache
            WHERE target_db = $2 AND schema_name = $3 AND embedding IS NOT NULL
              AND created_at > now() - ($4 * interval '1 second')
            ORDER BY embedding <=> CAST($1 AS vector)
            LIMIT 1
            """,
            str(qvec),
            target_db,
            schema,
            self._ttl,
        )
        if row is None or row["score"] < self._embedding_threshold:
            return None
        await self._bump_hit_count(target_db, schema, row["question"])
        return CacheEntry(row["question"], row["answer"], row["sql_steps"], row["hit_count"] + 1)

    async def store(
        self, question: str, target_db: str, answer: str, sql_steps: list[dict[str, Any]], schema: str = "public",
    ) -> None:
        """캐시에는 SQL 템플릿(sql_steps)을 저장한다. 실행 결과 원본은 저장하지 않는다
        — 대상 테이블 데이터 자체가 계속 바뀌기 때문이다. 저장 전 SQL은 반드시
        Canonicalization(§5.8)을 거친 형태여야 캐시 히트 시 일관된 출력이 보장된다."""
        embedding = await self._embed_fn(question) if self._embedding_enabled else None
        await self._pool.execute(
            """
            INSERT INTO pgxnl_cache (target_db, schema_name, question, answer, sql_steps, embedding)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            target_db,
            schema,
            question,
            answer,
            sql_steps,
            str(embedding) if embedding else None,
        )

    async def exists(self, question: str, target_db: str, schema: str = "public") -> bool:
        """정확히 같은 질문이 이미 들어 있는지.

        테이블에 `(target_db, schema_name, question)` 유니크 제약이 없다. 같은 질문을
        두 번 넣으면 행이 둘 생기고, `_bump_hit_count`의 UPDATE가 그 둘을 함께 올린다
        — 넣기 전에 호출자가 확인한다. TTL은 보지 않는다: 만료된 행도 지워지지 않고
        남아 있으므로 중복이 되는 것은 마찬가지다.
        """
        row = await self._pool.fetchrow(
            "SELECT 1 FROM pgxnl_cache WHERE target_db=$1 AND schema_name=$2 AND question=$3 LIMIT 1",
            target_db,
            schema,
            question,
        )
        return row is not None

    async def _bump_hit_count(self, target_db: str, schema: str, question: str) -> None:
        await self._pool.execute(
            "UPDATE pgxnl_cache SET hit_count = hit_count + 1 WHERE target_db=$1 AND schema_name=$2 AND question=$3",
            target_db,
            schema,
            question,
        )

    async def invalidate(self, target_db: str) -> None:
        await self._pool.execute("DELETE FROM pgxnl_cache WHERE target_db=$1", target_db)
