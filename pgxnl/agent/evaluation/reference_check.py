"""오답을 **대조 gold**와 비교해 "원본 gold 결함" 후보를 찾아낸다.

배경: BIRD gold에는 오류가 많다(Arcwise 분석 기준 Mini-Dev 16.7%, california_schools는
60%). 그래서 모델이 옳아도 오답 처리되는 문항이 생기는데, 이를 손으로 찾으려면 문항마다
gold SQL을 읽어야 한다.

이 모듈은 그 판정을 자동화한다 — 채점 기준(원본 gold)은 **건드리지 않고**, 오답 문항에
대해서만 대조 데이터셋(예: Arcwise 수정판)의 gold를 실행해 pred와 결과를 비교한다.

    pred == 대조 gold  이고  pred != 원본 gold   →  원본 gold 결함 후보

이건 어디까지나 **후보**다. 자동 등록하지 않고 사람이 확인해 `pgxnl_eval_gold_defects`에
등록한다 — 대조 데이터셋에도 오류가 있기 때문이다(실측: Arcwise의 qid 72는
`"Academic Year" BETWEEN 2014 AND 2015`인데 이 컬럼은 값이 `'2014-2015'` 하나뿐인 TEXT다).

사용:
    python -m pgxnl.agent.evaluation.reference_check <run_id> <대조_데이터셋.json>
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any

from pgxnl.agent.evaluation.bird import _results_equal


@dataclass
class ReferenceFinding:
    seq: int
    question_id: str
    verdict: str  # 'GOLD_DEFECT_CANDIDATE' | 'PRED_WRONG' | 'REFERENCE_SAME' | 'ERROR'
    detail: str = ""
    reference_sql: str = ""


# 판정 결과
GOLD_DEFECT_CANDIDATE = "GOLD_DEFECT_CANDIDATE"  # pred가 대조 gold와 일치 → 원본 gold가 의심스럽다
PRED_WRONG = "PRED_WRONG"  # 대조 gold와도 다르다 → 모델이 실제로 틀렸다
REFERENCE_SAME = "REFERENCE_SAME"  # 대조 gold가 원본과 같은 결과 → 대조군이 도움 안 됨
ERROR = "ERROR"


async def check_run(
    items: list, reference: dict[str, str], execute: Any,
) -> list[ReferenceFinding]:
    """items: EvalItem 리스트. reference: question_id -> 대조 gold SQL.
    execute: async (sql) -> rows. 대상 DB에서 읽기 전용으로 실행하는 함수."""
    out: list[ReferenceFinding] = []
    for it in items:
        if it.ex_pass:
            continue
        ref_sql = reference.get(str(it.question_id))
        pred = (it.pred_sql or "").strip()
        if not ref_sql or not pred:
            continue
        try:
            ref_rows = await execute(ref_sql)
            pred_rows = await execute(pred)
            gold_rows = await execute(it.gold_sql)
        except Exception as exc:  # noqa: BLE001 — 실행 실패도 진단 결과다
            out.append(ReferenceFinding(it.seq, str(it.question_id), ERROR,
                                        f"{type(exc).__name__}: {exc}"[:200], ref_sql))
            continue

        if _results_equal(gold_rows, ref_rows):
            verdict, detail = REFERENCE_SAME, "대조 gold가 원본과 같은 결과 — 판정 불가"
        elif _results_equal(pred_rows, ref_rows):
            verdict, detail = (
                GOLD_DEFECT_CANDIDATE,
                f"pred가 대조 gold와 일치(원본 {len(gold_rows)}행 / 대조·pred {len(ref_rows)}행)",
            )
        else:
            verdict, detail = (
                PRED_WRONG,
                f"대조 gold와도 다름(원본 {len(gold_rows)} / 대조 {len(ref_rows)} / pred {len(pred_rows)}행)",
            )
        out.append(ReferenceFinding(it.seq, str(it.question_id), verdict, detail, ref_sql))
    return out


def load_reference(path: str) -> dict[str, str]:
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    return {str(x["question_id"]): (x.get("SQL") or x.get("gold_sql") or "") for x in data}


def render(findings: list[ReferenceFinding]) -> str:
    from collections import Counter

    counts = Counter(f.verdict for f in findings)
    lines = [f"대조 대상 오답 {len(findings)}건", ""]
    for v, n in counts.most_common():
        lines.append(f"  {v:<24} {n}건")
    cands = [f for f in findings if f.verdict == GOLD_DEFECT_CANDIDATE]
    if cands:
        lines += ["", "★ 원본 gold 결함 후보 (사람이 확인 후 등록할 것):"]
        for f in cands:
            lines.append(f"  seq {f.seq} (qid {f.question_id}): {f.detail}")
    return "\n".join(lines)


async def _main(run_id: int, ref_path: str) -> None:
    import asyncpg

    from pgxnl.agent.evaluation.store import EvalStore
    from pgxnl.api.targets import TargetStore
    from pgxnl.settings import Settings

    s = Settings()
    sys_pool = await asyncpg.create_pool(s.system_pg_dsn, min_size=1, max_size=2)
    store = EvalStore(sys_pool)
    run = await store.get_run(run_id)
    if run is None:
        print(f"run {run_id}을 찾을 수 없습니다.")
        return
    items = await store.get_items(run_id, limit=10_000)
    target = await TargetStore(sys_pool, s.secret_key).get(run.target_name)
    await sys_pool.close()

    pool = await asyncpg.create_pool(target.dsn, min_size=1, max_size=2)
    schema = next((it.db_id for it in items if it.db_id), "public")

    async def execute(sql: str):
        async with pool.acquire() as conn:
            await conn.execute(f"SET search_path TO {schema}, public")
            return [dict(r) for r in await conn.fetch(sql)]

    findings = await check_run(items, load_reference(ref_path), execute)
    await pool.close()
    print(f"run {run_id} ({run.run_name}) — EX {run.correct_ex}/{run.total}\n")
    print(render(findings))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용: python -m pgxnl.agent.evaluation.reference_check <run_id> <대조_데이터셋.json>")
        raise SystemExit(1)
    asyncio.run(_main(int(sys.argv[1]), sys.argv[2]))
