"""BIRD 벤치마크 평가 실행기. 자연어 질문 -> 생성 SQL을 gold SQL과 비교해
EX(실행 결과 일치) / EM(정규화 텍스트 일치)을 채점한다.

pgxnl의 AnalysisResult.sql_steps는 항상 최대 1건(Canonicalization을 거친 최종
SQL)이므로 pred_sql 추출이 단순하다 — pgxrsa처럼 agent_steps에서 도구 호출
순서를 역추적할 필요가 없다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

from pgxnl.agent.evaluation.store import EvalItem, EvalStore

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], Awaitable[None]]

_cancel_events: dict[int, asyncio.Event] = {}

# 파일을 업로드하지 않았을 때 쓰는 번들 기본 BIRD MiniDev 데이터셋(500문항, db_id 포함).
DEFAULT_BIRD_DATASET_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "bird_minidev_pg.json"
# 평가 화면의 데이터셋 — 같은 평가 하네스(BIRD 형식 JSON)로 돈다. Northwind 는 docs/northwind_golden_set.json 을
# tools/northwind_dataset.py 로 변환한 것(날짜 +28년, 한글 질문, 2026-10-27).
DATASETS: dict[str, Path] = {
    "bird": DEFAULT_BIRD_DATASET_PATH,
    "northwind": DEFAULT_BIRD_DATASET_PATH.parent / "northwind_pg.json",
}


def request_cancel(run_id: int) -> None:
    ev = _cancel_events.get(run_id)
    if ev:
        ev.set()


def is_running(run_id: int) -> bool:
    return run_id in _cancel_events


def parse_bird_json(data: list[dict]) -> list[dict]:
    items = []
    for i, row in enumerate(data):
        sql = row.get("SQL") or row.get("gold_sql") or row.get("sql", "")
        if not sql:
            continue
        items.append({
            "seq": i,
            "question_id": str(row.get("question_id", i)),
            "db_id": row.get("db_id", "") or "public",
            "difficulty": row.get("difficulty", ""),
            "question": row.get("question", ""),
            "evidence": row.get("evidence", ""),
            "gold_sql": sql.strip(),
        })
    return items


def align_seq_to_default(items: list[dict], default_path: Path = DEFAULT_BIRD_DATASET_PATH) -> list[dict]:
    """업로드한 파일의 문항 번호(seq)를 기본 데이터셋의 번호로 맞춘다.

    seq 는 파일 안의 위치라, 몇 문항만 골라 올린 파일은 0, 1, 2 … 로 다시 매겨져 화면 번호가 전체 run 과
    달랐다(2026-10-14 사용자 요청). (db_id, question_id) 가 기본 데이터셋에 있으면 그 위치를 쓰고,
    없는 문항(다른 데이터셋)은 파일 안 위치를 그대로 둔다.
    """
    if not default_path.exists():
        return items
    try:
        default = parse_bird_json(json.loads(default_path.read_text()))
    except Exception:
        logger.warning("기본 데이터셋을 읽지 못해 seq 를 맞추지 않습니다", exc_info=True)
        return items
    index = {(it["db_id"], it["question_id"]): it["seq"] for it in default}
    for it in items:
        seq = index.get((it["db_id"], it["question_id"]))
        if seq is not None:
            it["seq"] = seq
    return items


#: 연속 이 횟수만큼 인프라 오류가 나면 run을 중단한다. 남은 문항을 계속 돌려봐야
#: 같은 오류만 쌓이고, 그렇게 만들어진 0/30이 나중에 측정값으로 오인된다(실측
#: 2026-09-03: watsonx 401로 3개 run, 임베딩 500으로 4개 run이 그렇게 기록됐다).
INFRA_FAILURE_ABORT_THRESHOLD = 5

#: 모델 품질이 아니라 외부 의존성 장애를 뜻하는 오류. 이런 실패로 만들어진 run은
#: 'infra_failed' 상태가 되어 정상 측정값과 구분된다.
_INFRA_ERROR_PATTERN = re.compile(
    r"토큰 발급 오류|임베딩 API 오류|watsonx API 오류|ConnectError|ConnectTimeout|"
    r"ReadTimeout|PoolTimeout|RemoteProtocolError|Connection refused",
    re.IGNORECASE,
)


def is_infrastructure_error(error: str | None) -> bool:
    """이 오류가 외부 의존성 장애인가 (모델이 못 푼 것이 아니라)."""
    return bool(error) and bool(_INFRA_ERROR_PATTERN.search(error))


async def run_evaluation(
    run_id: int,
    items: list[dict],
    orchestrator: Any,
    eval_store: EvalStore,
    *,
    user_id: int,
    on_progress: ProgressCallback | None = None,
    concurrency: int = 1,
) -> None:
    cancel_ev = asyncio.Event()
    _cancel_events[run_id] = cancel_ev

    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    done_count = correct_ex = correct_em = correct_ex_official = 0
    consecutive_infra_failures = 0
    aborted_by_infra = False

    async def _process(item: dict) -> None:
        nonlocal done_count, correct_ex, correct_em, correct_ex_official, consecutive_infra_failures, aborted_by_infra
        if cancel_ev.is_set():
            return

        t0 = time.monotonic()
        pred_sql: str | None = None
        ex_pass: bool | None = None
        ex_official: bool | None = None
        em_pass: bool | None = None
        error: str | None = None
        guards_fired: list[str] | None = None

        try:
            async with sem:
                if cancel_ev.is_set():
                    return
                try:
                    schema = item.get("db_id") or "public"
                    question = item["question"]
                    # evidence는 question 문자열에 미리 이어붙이지 않고 별도 인자로 넘긴다 —
                    # 질문 보강(enrichment)이 켜져 있으면 재작성 과정에서 evidence가 조용히
                    # 사라지는 문제가 있었다(orchestrator.analyze() docstring 참고).
                    # use_cache=False: 같은 30문항 배치를 규칙/glossary를 바꿔가며 반복
                    # 실행해 전후 비교하는 게 이 하네스의 핵심 용도라, 캐시를 켜두면
                    # 방금 바꾼 설정이 하나도 반영 안 된 예전 캐시 응답이 그대로
                    # 재사용돼 비교가 무의미해진다(orchestrator.analyze() docstring 참고).
                    analysis = await orchestrator.analyze(
                        question, user_id=user_id, schema=schema, evidence=item.get("evidence") or None,
                        use_cache=False,
                    )
                    pred_sql = analysis.sql_steps[-1]["sql"] if analysis.sql_steps else None
                    guards_fired = list(getattr(analysis, "guards_fired", None) or [])

                    if pred_sql:
                        try:
                            gold_rows = await orchestrator.execute_readonly(
                                item["gold_sql"], timeout_seconds=30, schema=schema
                            )
                        except Exception as exc:  # noqa: BLE001
                            error = f"gold SQL 실행 오류: {exc}"
                            ex_pass = False
                        else:
                            try:
                                pred_rows = await orchestrator.execute_readonly(
                                    pred_sql, timeout_seconds=30, schema=schema
                                )
                            except Exception as exc:  # noqa: BLE001
                                error = f"pred SQL 실행 오류: {exc}"
                                ex_pass = False
                            else:
                                ex_pass = _results_equal(gold_rows, pred_rows)
                                ex_official = results_equal_official(gold_rows, pred_rows)
                        em_pass = _sql_em(item["gold_sql"], pred_sql)
                    else:
                        # 실패한 SQL도 남긴다 — 없으면 화면에서 원인을 볼 수 없어 감사 로그를
                        # 뒤져야 했다(2026-10-06, seq 353). 채점은 그대로 실패.
                        pred_sql = getattr(analysis, "failed_sql", None)
                        # orchestrator.analyze()는 실행 시점 SQL 오류(예: 별칭이 잘못된
                        # 컬럼 참조)도 이제 예외를 던지는 대신 answer에 사유를 담아 정상
                        # 반환한다(§[10] 실행 단계 예외 처리) — 그 사유를 그대로 노출해야
                        # "SQL을 못 뽑음"과 "SQL은 뽑았는데 실행이 실패함"이 로그에서
                        # 구분된다.
                        error = analysis.answer or "분석 결과에서 SQL을 추출하지 못했습니다"
                        ex_pass = em_pass = ex_official = False
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # str(exc)만 쓰면 메시지 없는 예외(TimeoutError 등)가 빈 문자열이 되어
                    # "에러 없이 SQL만 안 나온" 것처럼 보인다 — 실제로 run 113에서 연속 9문항이
                    # 이렇게 기록돼, 인프라 실패를 모델 품질 문제로 오진하게 만들었다.
                    # 예외 종류를 항상 남긴다.
                    error = f"{type(exc).__name__}: {exc}" if str(exc) else f"{type(exc).__name__}(메시지 없음)"
                    ex_pass = em_pass = False
                    logger.warning(
                        "[Eval] run=%d seq=%d %s: %s", run_id, item["seq"], type(exc).__name__, exc,
                        exc_info=True,
                    )
        except asyncio.CancelledError:
            return

        elapsed = (time.monotonic() - t0) * 1000
        async with lock:
            done_count += 1
            if ex_pass:
                correct_ex += 1
            if em_pass:
                correct_em += 1
            if ex_official:
                correct_ex_official += 1
            snap_done, snap_ex, snap_em, snap_off = done_count, correct_ex, correct_em, correct_ex_official
            # 인프라 장애가 연속으로 나면 남은 문항은 돌려봐야 같은 오류만 쌓인다.
            if is_infrastructure_error(error):
                consecutive_infra_failures += 1
                if consecutive_infra_failures >= INFRA_FAILURE_ABORT_THRESHOLD and not cancel_ev.is_set():
                    aborted_by_infra = True
                    cancel_ev.set()
                    logger.error(
                        "[Eval] run=%d 인프라 오류 %d회 연속 — 중단합니다: %s",
                        run_id, consecutive_infra_failures, error,
                    )
            else:
                consecutive_infra_failures = 0

        await eval_store.add_item(EvalItem(
            run_id=run_id, seq=item["seq"], question_id=item["question_id"], db_id=item.get("db_id", ""),
            difficulty=item["difficulty"], question=item["question"], evidence=item["evidence"],
            gold_sql=item["gold_sql"], pred_sql=pred_sql, ex_pass=ex_pass, em_pass=em_pass,
            error=error, elapsed_ms=elapsed, ex_official=ex_official, guards_fired=guards_fired,
        ))
        await eval_store.update_progress(run_id, snap_done, snap_ex, snap_em, snap_off)

        if on_progress:
            try:
                await on_progress({
                    "type": "progress", "done": snap_done, "total": len(items),
                    "correct_ex": snap_ex, "correct_em": snap_em,
                    "seq": item["seq"], "question": item["question"][:80],
                    "ex_pass": ex_pass, "em_pass": em_pass, "error": error,
                })
            except Exception:  # noqa: BLE001
                pass

    final_status = "done"
    tasks = [asyncio.create_task(_process(item)) for item in items]
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
        if aborted_by_infra:
            # 'done'으로 남기면 0/30이 정상 측정값처럼 보인다 — 상태로 구분한다.
            final_status = "infra_failed"
        elif cancel_ev.is_set():
            final_status = "cancelled"
    except asyncio.CancelledError:
        final_status = "cancelled"
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        _cancel_events.pop(run_id, None)

    await eval_store.finish_run(run_id, final_status)
    if on_progress:
        try:
            await on_progress({"type": "done", "run_id": run_id, "status": final_status})
        except Exception:  # noqa: BLE001
            pass


def _norm_value(v: Any) -> Any:
    """PostgreSQL REAL(4바이트)과 DOUBLE PRECISION(8바이트) 정밀도 차이를 흡수한다.
    gold SQL(BIRD 원본이 SQLite→Postgres로 이식되며 CAST(x AS REAL)을 쓰는 경우가
    흔함)과 생성 SQL이 같은 값을 계산해도 캐스트 타입이 달라 문자열이 미세하게
    달라지는 걸 실측으로 확인했다(예: 0.9049080014228821 vs 0.9049079754601227,
    차이 2.6e-8). 소수점 5자리로 반올림해 이 차이를 흡수하고, 정수값(25.0)과
    정수(25)가 다른 문자열로 비교되지 않도록 정수로 통일한다."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float, Decimal)):
        rounded = round(float(v), 5)
        return int(rounded) if rounded == int(rounded) else rounded
    return str(v).strip().lower()


def _official_value(v):
    """set 에 넣으려면 해시 가능해야 한다. 값 자체는 바꾸지 않는다(공식 스크립트와 같게) —
    배열/JSON 같은 해시 불가 타입만 같은 내용의 해시 가능한 형태로 옮긴다."""
    if isinstance(v, list):
        return tuple(_official_value(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)
    return v


def results_equal_official(gold: list[dict], pred: list[dict]) -> bool:
    """공식 BIRD 채점 — `set(predicted_res) == set(ground_truth_res)`.
    중복·순서는 무시하고, 문자열 대소문자·공백·실수 오차는 **정규화하지 않는다**.
    근거: bird-bench/mini_dev evaluation/evaluation_ex.py `calculate_ex`(18~22행),
    AlibabaResearch/DAMO-ConvAI bird/llm/src/evaluation.py. (2026-10-06 확인)"""
    def rows(rs: list[dict]) -> set:
        return {tuple(_official_value(v) for v in r.values()) for r in rs}
    return rows(gold) == rows(pred)


async def rescore_official(orchestrator, eval_store, run_id: int) -> dict:
    """이미 끝난 run 의 공식 점수를 저장된 pred/gold SQL 을 다시 실행해 채운다(모델은 안 부른다)."""
    items = await eval_store.get_items(run_id, limit=10_000)
    scored = errors = 0
    for it in items:
        val: bool | None = None
        if it.pred_sql:
            try:
                schema = it.db_id or None
                gold = await orchestrator.execute_readonly(it.gold_sql, timeout_seconds=30, schema=schema)
                pred = await orchestrator.execute_readonly(it.pred_sql, timeout_seconds=30, schema=schema)
                val = results_equal_official(gold, pred)
                scored += 1
            except Exception:  # noqa: BLE001 — 실행 오류 문항은 None 으로 남긴다
                errors += 1
        await eval_store.set_official(it.id, val)
    total = await eval_store.recount_official(run_id)
    return {"run_id": run_id, "correct_ex_official": total, "scored": scored, "errors": errors, "items": len(items)}


def _results_equal(r1: list[dict], r2: list[dict]) -> bool:
    def norm_row(row: dict) -> tuple:
        return tuple(_norm_value(v) for v in row.values())
    # LEFT JOIN 등으로 일부 행만 NULL(빈 문자열로 정규화됨)이고 나머지는 숫자인 컬럼이
    # 섞이면, 파이썬 기본 sorted()가 같은 위치의 문자열과 숫자를 직접 비교하려다
    # TypeError('<' not supported between instances of 'str' and 'int')를 던지는 걸
    # 실측으로 확인했다 — 이 경우 그 문항 전체가 "채점 불가 오류"로 조용히 넘어가버려
    # 실제 EX 결과를 확인할 기회조차 없었다. 정렬은 두 리스트를 같은 기준으로 줄 세워
    # 순서 무관 비교를 하기 위한 수단일 뿐 "숫자로서의 대소"가 필요한 게 아니므로,
    # 정렬 키를 문자열로 통일해 타입이 섞여도 항상 비교 가능하게 만든다.
    def sort_key(row: tuple) -> tuple:
        return tuple(str(v) for v in row)
    return (
        sorted((norm_row(r) for r in r1), key=sort_key)
        == sorted((norm_row(r) for r in r2), key=sort_key)
    )


def _sql_em(gold: str, pred: str) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.lower().strip().rstrip(";"))
    return norm(gold) == norm(pred)
