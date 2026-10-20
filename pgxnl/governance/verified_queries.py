"""승인된 사용례 — 수집된 실행 SQL에 자연어 설명을 붙여 사람이 승인한 것.

**시맨틱 캐시와 소비자가 다르다.**

```
pgxnl_cache              질문 -> SQL   파이프라인이 읽는다   TTL 있음   자동 축적
pgxnl_verified_queries   질문 -> SQL   사람이 읽는다        TTL 없음   승인해야 보임
```

캐시는 같은 질문의 반복을 건너뛰는 장치이고, 이쪽은 **새 질의를 쓸 때 참고하는 예제**다.
같은 (질문, SQL) 쌍이 양쪽에 있어도 문제가 아니다 — 하는 일과 수명이 다르다.

## 유사도로 순위를 매기고, 테이블로 거른다

**임계값이 없다.** 이게 캐시와의 결정적 차이다. 캐시는 임계값을 넘으면 자동으로 하나를
골라 내보내므로 빗나가면 조용한 오답이 된다(실측: "가장 적게 대여된"이 "가장 많이
대여된"에 0.923 — 방향을 담지 못한다). 여기는 사람이 목록을 보고 고르므로 빗나간
항목이 섞여도 눈으로 걸러진다. **순위만 맞으면 된다.**

그래서 캐시에서 "못 쓸 근거"였던 측정이 여기서는 "쓸 근거"가 된다 — 같은 뜻 0.83~0.98,
다른 뜻 최고 0.93. 하나를 자동 선택하기엔 겹치지만 5개를 순위로 보여주기엔 충분하다.

임베딩이 없으면(비활성이거나 서버 장애) `pg_trgm` 어휘 유사도로 내려앉는다. 이 화면이
임베딩 서버에 묶이면 안 된다 — 참고용 화면이 안 뜨는 것보다 덜 똑똑하게 뜨는 게 낫다.

테이블 필터(`tables_used`)는 보조 축이다. "rental 을 쓰는 것만" 처럼 좁힐 때 쓴다.

## 승인이 있는 이유

수집 원본은 절반 가까이가 쓰레기다(실측: dvdrental 20건 중 8건이
`SELECT pg_advisory_unlock_all()`, `set_config(...)` 같은 드라이버 잡음). 그건
기계가 거른다. 기계가 못 거르는 건 **설명이 맞느냐**다 — 틀린 설명이 붙은 예제는
없느니만 못하다. 승인 절차의 본체가 거기에 있다.

## $N 을 그대로 둔다

`pg_stat_statements` 가 값을 지운 자리표시자(`WHERE rental_date > $1`)를 대표값으로
채우지 않는다. 원문을 보존하는 편이 정직하고, "여기에 값이 들어간다"가 오히려 명확하다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import asyncpg

_WS = re.compile(r"\s+")


def sql_hash(sql: str) -> str:
    """같은 SQL 재등록을 막기 위한 키. 공백만 정규화한다 — 대소문자나 별칭까지
    건드리면 의미가 다른 SQL 을 같은 것으로 볼 수 있다."""
    return hashlib.sha256(_WS.sub(" ", sql.strip()).encode()).hexdigest()


@dataclass
class VerifiedQuery:
    id: int
    target_name: str
    schema_name: str
    question: str
    sql_text: str
    tables_used: list[str]
    has_pii: bool
    approved: bool
    created_at: Any
    approved_at: Any = None
    #: 유사 순위 점수. 검색어가 없으면 None — 판정이 아니라 정렬용이다.
    score: float | None = None


def _row(r: asyncpg.Record) -> VerifiedQuery:
    return VerifiedQuery(
        id=r["id"], target_name=r["target_name"], schema_name=r["schema_name"],
        question=r["question"], sql_text=r["sql_text"],
        tables_used=list(r["tables_used"] or []), has_pii=r["has_pii"],
        approved=r["approved"], created_at=r["created_at"], approved_at=r["approved_at"],
        score=float(r["score"]) if r.get("score") is not None else None,
    )


class VerifiedQueryStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def add(
        self, target_name: str, question: str, sql_text: str, *,
        schema_name: str = "public", tables_used: list[str] | None = None,
        has_pii: bool = False, created_by: int | None = None,
        embedding: list[float] | None = None,
    ) -> int | None:
        """등록한다. 승인은 따로 한다 — 등록 시점에는 항상 `approved=false` 다.

        같은 SQL 이 이미 있으면 None 을 돌려준다. 덮어쓰지 않는 이유는 기존 항목이
        이미 승인돼 설명이 다듬어져 있을 수 있기 때문이다.
        """
        return await self._pool.fetchval(
            """
            INSERT INTO pgxnl_verified_queries
                (target_name, schema_name, question, sql_text, sql_hash,
                 tables_used, has_pii, created_by, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (target_name, sql_hash) DO NOTHING
            RETURNING id
            """,
            target_name, schema_name, question.strip(), sql_text,
            sql_hash(sql_text), tables_used or [], has_pii, created_by,
            str(embedding) if embedding else None,
        )

    async def list(
        self, target_name: str | None = None, *, schema_name: str | None = None,
        table: str | None = None, q: str | None = None, q_embedding: list[float] | None = None,
        approved_only: bool = False, limit: int = 100, offset: int = 0,
    ) -> tuple[int, list[VerifiedQuery]]:
        """`approved_only` 는 호출자가 정한다 — 일반 사용자 경로는 반드시 True 로
        부른다(라우트에서 강제). 관리 화면은 미승인까지 본다.

        `q` 가 있으면 **거르지 않고 순위만 매긴다.** 임계값을 두지 않는 이유는 모듈
        설명에 적었다 — 사람이 목록에서 고르므로 빗나간 항목이 섞이는 비용이 낮고,
        반대로 임계값 때문에 목록이 비어버리면 화면이 쓸모없어진다.

        순위 재료는 두 가지다. `q_embedding` 이 있으면 코사인 유사도를, 없으면
        `pg_trgm` 어휘 유사도를 쓴다. 임베딩이 있는 항목과 없는 항목이 섞여 있을 수
        있어서(나중에 켠 경우) 임베딩이 NULL 이면 trgm 점수로 대신한다.
        """
        where, args = ["TRUE"], []
        if target_name:
            args.append(target_name)
            where.append(f"target_name = ${len(args)}")
        if schema_name:
            args.append(schema_name)
            where.append(f"schema_name = ${len(args)}")
        if approved_only:
            where.append("approved")
        if table:
            # 수집 쪽이 'public.rental' 처럼 스키마를 붙여 넣기도 하고 'rental' 만
            # 넣기도 해서 둘 다 본다.
            args.append(table)
            args.append(f"%.{table}")
            where.append(
                f"EXISTS (SELECT 1 FROM jsonb_array_elements_text(tables_used) t"
                f"        WHERE t = ${len(args) - 1} OR t ILIKE ${len(args)})"
            )
        clause = " AND ".join(where)

        total = await self._pool.fetchval(
            f"SELECT count(*) FROM pgxnl_verified_queries WHERE {clause}", *args
        )

        if q and q_embedding:
            args.extend([str(q_embedding), q])
            score = (
                f"COALESCE(1 - (embedding <=> CAST(${len(args) - 1} AS vector)),"
                f" similarity(question, ${len(args)}))"
            )
        elif q:
            args.append(q)
            score = f"GREATEST(similarity(question, ${len(args)}), similarity(sql_text, ${len(args)}))"
        else:
            score = "NULL::real"

        rows = await self._pool.fetch(
            f"""
            SELECT id, target_name, schema_name, question, sql_text, tables_used,
                   has_pii, approved, created_at, approved_at, {score} AS score
            FROM pgxnl_verified_queries WHERE {clause}
            ORDER BY {"score DESC NULLS LAST, " if q else ""}approved DESC, created_at DESC
            LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
            """,
            *args, limit, offset,
        )
        return total, [_row(r) for r in rows]

    async def update(
        self, entry_id: int, *, question: str | None = None, sql_text: str | None = None,
    ) -> bool:
        """승인 전에 설명을 고치는 용도. SQL 을 고치면 해시도 따라 바뀐다."""
        sets, args = [], []
        if question is not None:
            args.append(question.strip())
            sets.append(f"question = ${len(args)}")
        if sql_text is not None:
            args.append(sql_text)
            sets.append(f"sql_text = ${len(args)}")
            args.append(sql_hash(sql_text))
            sets.append(f"sql_hash = ${len(args)}")
        if not sets:
            return False
        args.append(entry_id)
        got = await self._pool.fetchval(
            f"UPDATE pgxnl_verified_queries SET {', '.join(sets)} WHERE id = ${len(args)} RETURNING id",
            *args,
        )
        return got is not None

    async def set_approved(self, entry_id: int, approved: bool, *, user_id: int | None = None) -> bool:
        got = await self._pool.fetchval(
            """
            UPDATE pgxnl_verified_queries
            SET approved = $2,
                -- ELSE NULL 이 타입을 안 주므로 $3 을 명시적으로 캐스트한다 —
                -- 안 하면 text 로 추론돼 DatatypeMismatchError 가 난다.
                approved_by = CASE WHEN $2 THEN $3::integer ELSE NULL END,
                approved_at = CASE WHEN $2 THEN now() ELSE NULL END
            WHERE id = $1 RETURNING id
            """,
            entry_id, approved, user_id,
        )
        return got is not None

    async def delete(self, entry_id: int) -> bool:
        got = await self._pool.fetchval(
            "DELETE FROM pgxnl_verified_queries WHERE id = $1 RETURNING id", entry_id
        )
        return got is not None
