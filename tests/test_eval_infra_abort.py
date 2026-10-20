"""인프라 장애 시 평가 조기 중단 테스트 (`run_evaluation`).

배경(실측 2026-09-03): watsonx 토큰 401로 3개 run, 임베딩 API 500으로 4개 run이
30문항 전부 실패하며 `status='done', 0/30`으로 기록됐다. 남은 문항을 계속 돌려봐야
같은 오류만 쌓이고, 그렇게 만들어진 0/30은 나중에 측정값으로 오인된다(실제로 손으로
`[오염:...]` 표시를 붙여 걸러내야 했다).
"""
from __future__ import annotations

import pytest

from pgxnl.agent.evaluation.bird import (
    INFRA_FAILURE_ABORT_THRESHOLD,
    is_infrastructure_error,
    run_evaluation,
)


@pytest.mark.parametrize("error", [
    "RuntimeError: watsonx CPD 토큰 발급 오류 401: Unauthorized",
    "RuntimeError: watsonx 임베딩 API 오류 500: connection refused",
    "ConnectError: [Errno 111] Connection refused",
    "ReadTimeout: ",
])
def test_infrastructure_errors_are_recognised(error):
    assert is_infrastructure_error(error)


@pytest.mark.parametrize("error", [
    None, "",
    "pred SQL 실행 오류: column t1.foo does not exist",
    "존재하지 않는 테이블을 참조했습니다: california_schools.fpm",
    "분석 결과에서 SQL을 추출하지 못했습니다",
])
def test_model_failures_are_not_infrastructure(error):
    """모델이 못 푼 것을 인프라 장애로 오인하면 정상 run이 중단된다."""
    assert not is_infrastructure_error(error)


class _FakeStore:
    def __init__(self) -> None:
        self.items: list = []
        self.final_status: str | None = None

    async def add_item(self, item):
        self.items.append(item)

    async def update_progress(self, *a, **kw):
        pass

    async def finish_run(self, run_id, status):
        self.final_status = status


class _BoomOrchestrator:
    """모든 문항에서 인프라 오류를 낸다."""

    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, *a, **kw):
        self.calls += 1
        raise RuntimeError("watsonx CPD 토큰 발급 오류 401: Unauthorized")


class _ModelFailureOrchestrator:
    """SQL을 못 만든다 — 인프라가 아니라 모델 실패다."""

    def __init__(self) -> None:
        self.calls = 0

    async def analyze(self, *a, **kw):
        self.calls += 1
        raise ValueError("SQL 생성 실패")


def _items(n: int) -> list[dict]:
    return [{
        "seq": i, "question_id": i, "db_id": "d", "difficulty": "simple",
        "question": "q", "evidence": "", "gold_sql": "SELECT 1",
    } for i in range(n)]


@pytest.mark.asyncio
async def test_run_aborts_after_consecutive_infra_failures():
    store, orc = _FakeStore(), _BoomOrchestrator()
    await run_evaluation(9001, _items(30), orc, store, user_id=1, concurrency=1)
    assert store.final_status == "infra_failed"          # 'done'이면 0/30이 측정값처럼 보인다
    assert orc.calls <= INFRA_FAILURE_ABORT_THRESHOLD + 1
    assert len(store.items) < 30


@pytest.mark.asyncio
async def test_model_failures_do_not_abort_the_run():
    """모델이 30문항 내내 실패해도 그건 유효한 측정 결과다 — 끝까지 돌려야 한다."""
    store, orc = _FakeStore(), _ModelFailureOrchestrator()
    await run_evaluation(9002, _items(12), orc, store, user_id=1, concurrency=1)
    assert store.final_status == "done"
    assert orc.calls == 12
    assert len(store.items) == 12
