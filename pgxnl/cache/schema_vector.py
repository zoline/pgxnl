"""pgvector 기반 스키마 링킹 (Schema RAG). design 문서 §5.4 참고.

SQLAlchemy 주의사항: text()에서 ':param::vector' 문법은 파라미터 인식 오류를 일으키므로
반드시 CAST(:param AS vector)를 사용한다 (raw asyncpg 사용 시에도 동일한 습관을 유지).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import asyncpg

from pgxnl.agent.mschema import to_light_doc, to_mschema
from pgxnl.connectors.base import TableMeta
from pgxnl.llm.embeddings import EmbedFn

logger = logging.getLogger(__name__)


@dataclass
class TableCandidate:
    schema: str
    table: str
    mschema: str
    score: float


def filter_by_score_margin(candidates: list[TableCandidate], margin: float) -> list[TableCandidate]:
    """1위 후보 점수 대비 margin 이내인 것만 남긴다. top_k는 상한일 뿐 관련성을
    보장하지 않아, 점수 하위권 후보가 질문과 무관해도 그대로 컨텍스트에 채워지는
    문제(§5.4)를 완화한다. candidates는 이미 score 내림차순으로 정렬돼 있다고
    가정한다(search()가 ORDER BY로 정렬해서 넘겨준다). margin<=0이면 필터링하지
    않는다(기존 top_k 그대로 동작 — 하위 호환)."""
    if not candidates or margin <= 0:
        return candidates
    top_score = candidates[0].score
    return [c for c in candidates if c.score >= top_score - margin]


class SchemaVectorIndex:
    def __init__(self, pool: asyncpg.Pool, embed_fn: EmbedFn | None, target_name: str) -> None:
        self._pool = pool
        self._embed_fn = embed_fn
        self._target_name = target_name

    @property
    def enabled(self) -> bool:
        return self._embed_fn is not None

    async def _approved_joins(self, tables: list[TableMeta]) -> dict[str, list[tuple[str, str, str]]]:
        """승인된 조인 그래프를 `{테이블: [(내 컬럼, 상대 테이블, 상대 컬럼), ...]}`로.

        `tables` 가 속한 스키마의 관계와 스키마 미상('') 관계만 본다(graph.list_edges 의 schema
        필터, 2026-10-07) — 전엔 대상 전체의 관계를 맨 이름으로만 맞춰 다른 스키마의 같은 이름
        테이블에 붙을 수 있었다. **FK로 이미 드러나는 부모-자식 관계는 빼고**, `[Foreign Keys]`에
        없는 관계만 남긴다 — 같은 내용을 두 섹션에 적으면 프롬프트만 길어진다.
        """
        from pgxnl.agent.discovery.graph import list_edges

        schemas = {t.schema.lower() for t in tables}
        if len(schemas) != 1:
            return {}  # 스키마 하나 단위로만 계산한다(build_all 이 스키마별로 부른다)
        try:
            edges = await list_edges(self._pool, self._target_name, only_reviewed=True, schema=schemas.pop())
        except Exception:  # 그래프 조회 실패는 색인을 막을 사유가 아니다
            logger.warning("승인된 조인 그래프 조회 실패, FK로 대체합니다", exc_info=True)
            return {}

        names = {t.name.lower() for t in tables}
        # FK 는 양방향으로 센다 — 자식 쪽에서만 빼면 부모 쪽에 같은 관계가 역방향으로 남아
        # `[Foreign Keys]`와 중복됐다(2026-10-12, california schools 블록에 frpm·satscores 2건).
        declared = set()
        for t in tables:
            for local, ref_table, ref_col in t.foreign_keys:
                a = (t.name.lower(), local.lower())
                b = (ref_table.split(".")[-1].lower(), ref_col.lower())
                declared.add((*a, *b))
                declared.add((*b, *a))
        out: dict[str, list[tuple[str, str, str]]] = {}
        for e in edges:
            ta, tb = e.table_a.lower(), e.table_b.lower()
            if ta not in names or tb not in names:
                continue
            for name, col, other, other_col in (
                (ta, e.column_a, tb, e.column_b), (tb, e.column_b, ta, e.column_a),
            ):
                if (name, col.lower(), other, other_col.lower()) in declared:
                    continue  # [Foreign Keys]에 이미 있다
                out.setdefault(name, []).append((col, other, other_col))
        return out

    async def index_table(
        self, table: TableMeta, canonical: dict[str, dict[str, str]] | None = None,
        siblings: list[tuple[str, str, str]] | None = None,
    ) -> bool:
        """테이블 하나를 임베딩해 저장. 성공하면 True. 임베딩 자체가 실패해도(예: 컬럼이
        매우 많은 테이블이 임베딩 모델의 최대 시퀀스 길이를 넘기는 경우) 그 테이블만
        건너뛰고 False를 반환한다 — build_all()이 배치 전체를 계속 진행할 수 있어야
        한다(테이블 하나의 실패로 나머지 스키마 전체의 재색인이 죽으면 안 된다)."""
        if not self.enabled:
            return False
        light_doc = to_light_doc(table)
        try:
            embedding = await self._embed_fn(light_doc)
        except Exception:  # 배치 전체를 죽이지 않기 위해 개별 실패만 기록하고 계속
            logger.warning(
                "스키마 벡터 임베딩 실패, 건너뜀: %s.%s.%s", self._target_name, table.schema, table.name,
                exc_info=True,
            )
            return False
        mschema = to_mschema(table, (canonical or {}).get(table.name), siblings)
        await self._pool.execute(
            """
            INSERT INTO pgxnl_schema_vectors
                (target_name, schema_name, table_name, doc, mschema, embedding, indexed_at)
            VALUES ($1, $2, $3, $4, $5, $6, now())
            ON CONFLICT (target_name, schema_name, table_name)
            DO UPDATE SET doc=EXCLUDED.doc, mschema=EXCLUDED.mschema,
                          embedding=EXCLUDED.embedding, indexed_at=now()
            """,
            self._target_name,
            table.schema,
            table.name,
            light_doc,
            mschema,
            str(embedding),
        )
        return True

    async def build_all(
        self, tables: list[TableMeta], canonical: dict[str, dict[str, str]] | None = None,
        only: set[str] | None = None,
    ) -> int:
        """반환값은 성공적으로 색인된 테이블 수(전체 시도 수가 아님).

        `canonical`은 `{테이블: {컬럼: 표시문구}}` — Design Lab이 찾은 "이 컬럼은 저
        컬럼의 사본" 관계를 mschema 컬럼 줄에 실어 넣는다(§Design Lab). mschema는
        색인 시점에 미리 계산돼 저장되므로, 정본 판정이 바뀌면 재색인해야 한다.
        """
        # `only`: 조인 관계는 `tables`(스키마 전체) 기준으로 계산하되 이 이름의 테이블만
        # 저장한다. 테이블 하나만 넘기면 형제·승인 조인 계산이 그 하나로 좁아져
        # [Direct Joins]가 빠진다 — 단일 재색인이 전체 재구축과 다른 형식으로 저장될 수
        # 있었다(schema_include_sibling_joins 를 켠 경우. 2026-10-02 현재 기본 false 라 동일).
        #
        # [Direct Joins]에 넣을 관계. **승인된 조인 그래프**(pgxnl_join_candidates의
        # reviewed=true)는 **항상** 넣는다 — 사람이 검토해 승인한 관계라 FK 선언에 없는
        # 관계까지 담고(예: frpm.cdscode = satscores.cds, cards.setcode = sets.code), 승인
        # 자체가 스키마 단위 스위치다(2026-10-07 사용자 결정. 전엔 아래 전역 실험 스위치에
        # 함께 묶여 있었다). 승인된 관계가 없을 때만, 전역 스위치가 켜져 있으면 FK에서
        # 형제 조인을 계산해 채운다(§mschema.sibling_joins — california 에서 중립~음수).
        from pgxnl.agent.mschema import sibling_joins
        from pgxnl.settings import settings as _settings

        sibs = await self._approved_joins(tables)
        if not sibs and _settings.schema_include_sibling_joins:
            sibs = sibling_joins(tables)
        succeeded = 0
        for t in tables:
            if only is not None and t.name not in only:
                continue
            if await self.index_table(t, canonical, sibs.get(t.name)):
                succeeded += 1
        return succeeded

    async def search(
        self, question: str, top_k: int, *, score_margin: float = 0.0, schema: str | None = None,
        keep_all_max: int = 0,
    ) -> list[TableCandidate]:
        """schema: BIRD처럼 target_name 하나에 스키마가 여러 개면, 필터 없이 target_name만으로
        검색할 경우 다른 스키마의 무관한 테이블이 임베딩 유사도만으로 후보에 섞여 들어올 수
        있다(실측 확인 — SQL 텍스트를 그대로 질문으로 쓰는 SQL 튜닝에서 특히 두드러졌지만,
        자연어 질문 경로도 근본적으로 같은 위험을 안고 있었다). 지정하면 해당 스키마로만
        제한한다."""
        if not self.enabled:
            return []
        qvec = await self._embed_fn(question)
        rows = await self._pool.fetch(
            """
            SELECT schema_name, table_name, mschema,
                   1 - (embedding <=> CAST($1 AS vector)) AS score
            FROM pgxnl_schema_vectors
            WHERE target_name = $2 AND ($4::text IS NULL OR schema_name = $4)
            ORDER BY embedding <=> CAST($1 AS vector)
            LIMIT $3
            """,
            str(qvec),
            self._target_name,
            top_k,
            schema,
        )
        candidates = [
            TableCandidate(schema=r["schema_name"], table=r["table_name"], mschema=r["mschema"], score=r["score"])
            for r in rows
        ]
        # 테이블이 몇 개 안 되는 스키마는 전부 넣는다(2026-10-15 사용자, keep_all_max=3). 줄여 봐야 얻는 게 없고
        # 필요한 테이블이 빠질 위험만 있다 — 마진 0.10 에서 california(3개) 449 가 schools 를 잃었다.
        # LIMIT 에 걸리지 않고 다 돌아왔을 때만 "스키마 전체"로 본다.
        if schema and keep_all_max and len(candidates) <= keep_all_max and len(candidates) < top_k:
            return candidates
        return filter_by_score_margin(candidates, score_margin)

    async def indexed_tables(self) -> dict[str, set[str]]:
        """스키마 -> 색인된 테이블 이름 집합."""
        rows = await self._pool.fetch(
            "SELECT schema_name, table_name FROM pgxnl_schema_vectors WHERE target_name=$1", self._target_name
        )
        out: dict[str, set[str]] = {}
        for r in rows:
            out.setdefault(r["schema_name"], set()).add(r["table_name"])
        return out

    async def invalidate(self) -> None:
        await self._pool.execute("DELETE FROM pgxnl_schema_vectors WHERE target_name=$1", self._target_name)

    async def stats(self) -> int:
        row = await self._pool.fetchrow(
            "SELECT count(*) AS n FROM pgxnl_schema_vectors WHERE target_name=$1", self._target_name
        )
        return row["n"]
