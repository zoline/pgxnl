"""BIRD 벤치마크 평가 실행/항목 저장소. pgxnl_eval_runs / pgxnl_eval_items."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import asyncpg


@dataclass
class EvalRun:
    id: int
    target_name: str
    run_name: str
    status: str
    total: int
    done: int
    correct_ex: int
    correct_em: int
    created_at: datetime
    finished_at: datetime | None
    #: 공식 BIRD 채점(set 비교) 정답 수. None = 미계산(열 추가 전 run).
    correct_ex_official: int | None = None

    @property
    def ex_official_pct(self) -> float | None:
        if self.correct_ex_official is None or not self.total:
            return None
        return round(self.correct_ex_official / self.total * 100, 2)

    @property
    def ex_pct(self) -> float:
        return round(self.correct_ex / self.total * 100, 2) if self.total else 0.0

    @property
    def em_pct(self) -> float:
        return round(self.correct_em / self.total * 100, 2) if self.total else 0.0


@dataclass
class EvalItem:
    run_id: int
    seq: int = 0
    question_id: str = ""
    db_id: str = ""
    difficulty: str = ""
    question: str = ""
    evidence: str = ""
    gold_sql: str = ""
    pred_sql: str | None = None
    ex_pass: bool | None = None
    em_pass: bool | None = None
    error: str | None = None
    elapsed_ms: float = 0.0
    id: int | None = None
    #: 공식 BIRD 채점(set 비교). None = 미계산 또는 채점 불가(실행 오류 등).
    ex_official: bool | None = None
    #: 루프 안 가드 발동 순서(예: ["aggregate_mix", "literal"]). None = 기록 전 run.
    guards_fired: list[str] | None = None


class EvalStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_run(self, target_name: str, run_name: str, total: int) -> int:
        row = await self._pool.fetchrow(
            "INSERT INTO pgxnl_eval_runs (target_name, run_name, total, correct_ex_official) VALUES ($1, $2, $3, 0) RETURNING id",
            target_name, run_name, total,
        )
        return row["id"]

    async def update_progress(
        self, run_id: int, done: int, correct_ex: int, correct_em: int, correct_ex_official: int | None = None,
    ) -> None:
        await self._pool.execute(
            "UPDATE pgxnl_eval_runs SET done=$1, correct_ex=$2, correct_em=$3, "
            "correct_ex_official=COALESCE($5, correct_ex_official) WHERE id=$4",
            done, correct_ex, correct_em, run_id, correct_ex_official,
        )

    async def set_official(self, item_id: int, ex_official: bool | None) -> None:
        await self._pool.execute("UPDATE pgxnl_eval_items SET ex_official=$1 WHERE id=$2", ex_official, item_id)

    async def recount_official(self, run_id: int) -> int:
        n = await self._pool.fetchval(
            "SELECT count(*) FILTER (WHERE ex_official) FROM pgxnl_eval_items WHERE run_id=$1", run_id
        )
        await self._pool.execute("UPDATE pgxnl_eval_runs SET correct_ex_official=$1 WHERE id=$2", n, run_id)
        return n

    async def finish_run(self, run_id: int, status: str = "done") -> None:
        await self._pool.execute(
            "UPDATE pgxnl_eval_runs SET status=$1, finished_at=now() WHERE id=$2", status, run_id
        )

    async def add_item(self, item: EvalItem) -> None:
        await self._pool.execute(
            """
            INSERT INTO pgxnl_eval_items
                (run_id, seq, question_id, db_id, difficulty, question, evidence,
                 gold_sql, pred_sql, ex_pass, em_pass, error, elapsed_ms, ex_official, guards_fired)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            """,
            item.run_id, item.seq, item.question_id, item.db_id, item.difficulty, item.question, item.evidence,
            item.gold_sql, item.pred_sql, item.ex_pass, item.em_pass, item.error, item.elapsed_ms, item.ex_official,
            item.guards_fired,
        )

    async def list_runs(
        self, target_name: str, *, limit: int | None = None, offset: int = 0
    ) -> list[EvalRun]:
        """최신순 목록. limit을 주면 페이지 단위로 가져온다 — 이력이 쌓이면(실측 82건)
        화면에서 최근 것을 찾기 어려워진다. **지우지 않고 페이지로 나눈다**: 이력은
        이 프로젝트의 유일한 사실 근거라(문서의 수치를 재확인하는 유일한 방법)
        용량(2.2MB)이 문제가 아닌 한 보존한다."""
        sql = "SELECT * FROM pgxnl_eval_runs WHERE target_name = $1 ORDER BY created_at DESC"
        params: list = [target_name]
        if limit is not None:
            params += [limit, offset]
            sql += f" LIMIT ${len(params) - 1} OFFSET ${len(params)}"
        return [EvalRun(**dict(r)) for r in await self._pool.fetch(sql, *params)]

    async def count_runs(self, target_name: str) -> int:
        return await self._pool.fetchval(
            "SELECT count(*) FROM pgxnl_eval_runs WHERE target_name = $1", target_name
        )

    async def get_run(self, run_id: int) -> EvalRun | None:
        row = await self._pool.fetchrow("SELECT * FROM pgxnl_eval_runs WHERE id = $1", run_id)
        return EvalRun(**dict(row)) if row else None

    async def get_items(
        self, run_id: int, *, limit: int = 200, offset: int = 0, only_wrong: bool = False
    ) -> list[EvalItem]:
        if only_wrong:
            rows = await self._pool.fetch(
                """
                SELECT * FROM pgxnl_eval_items WHERE run_id = $1 AND (ex_pass = false OR em_pass = false)
                ORDER BY seq LIMIT $2 OFFSET $3
                """,
                run_id, limit, offset,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT * FROM pgxnl_eval_items WHERE run_id = $1 ORDER BY seq LIMIT $2 OFFSET $3",
                run_id, limit, offset,
            )
        return [EvalItem(**dict(r)) for r in rows]

    async def delete_run(self, run_id: int) -> bool:
        row = await self._pool.fetchrow("DELETE FROM pgxnl_eval_runs WHERE id = $1 RETURNING id", run_id)
        return row is not None


@dataclass
class GoldDefect:
    """벤치마크 정답(gold)이 틀린 문항. 모델이 옳아도 오답 처리되는 케이스."""

    id: int
    target_name: str
    db_id: str
    question_id: str
    reason: str
    evidence: str | None
    created_at: datetime


class GoldDefectStore:
    """gold 결함 등록부.

    **EX 계산에는 절대 개입하지 않는다** — strict EX가 리더보드와 비교 가능한 유일한
    수치이므로 그대로 두고, 화면 표시와 "결함 제외 EX"라는 부가 정보로만 쓴다.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_for(self, target_name: str) -> list[GoldDefect]:
        rows = await self._pool.fetch(
            "SELECT * FROM pgxnl_eval_gold_defects WHERE target_name = $1 ORDER BY db_id, question_id",
            target_name,
        )
        return [GoldDefect(**dict(r)) for r in rows]

    async def as_map(self, target_name: str) -> dict[tuple[str, str], GoldDefect]:
        """(db_id, question_id) -> GoldDefect. 평가 항목에 표시를 붙일 때 쓴다."""
        return {(d.db_id, d.question_id): d for d in await self.list_for(target_name)}

    async def upsert(
        self, target_name: str, db_id: str, question_id: str, reason: str, evidence: str | None = None
    ) -> int:
        return await self._pool.fetchval(
            """
            INSERT INTO pgxnl_eval_gold_defects (target_name, db_id, question_id, reason, evidence)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (target_name, db_id, question_id)
            DO UPDATE SET reason = EXCLUDED.reason, evidence = EXCLUDED.evidence
            RETURNING id
            """,
            target_name, db_id, question_id, reason, evidence,
        )

    async def delete(self, defect_id: int) -> bool:
        row = await self._pool.fetchrow(
            "DELETE FROM pgxnl_eval_gold_defects WHERE id = $1 RETURNING id", defect_id
        )
        return row is not None
