"""조언형 가드가 되돌린 SQL을 후보로 기억한다 (2026-10-07, california seq 467).

조언형 가드는 SQL 을 한 번 되돌려 보내기만 하고 저장하지 않았다. 모델이 고쳐 다시 내지 않고 바로
finalize 하면 "SQL 없음"으로 끝나 설명문만 반환됐다. 이제 되돌린 SQL 을 last_sql[1] 에 둔다.
"""
from __future__ import annotations

import asyncio

import pytest

from pgxnl.agent.orchestrator import Orchestrator
from pgxnl.parsing.postgresql_parser import AntlrPostgresParser
from pgxnl.settings import Settings

SQL = "SELECT admemail1 FROM schools WHERE county = 'San Bernardino'"


class _Warn:
    def message(self) -> str:
        return "조언: 이 값은 여러 컬럼에 흔합니다"


async def _none(*_a, **_k):
    return None


async def _empty(*_a, **_k):
    return []


def _orchestrator(advise: bool) -> Orchestrator:
    orc = Orchestrator(object(), Settings(), llm=None, parser=AntlrPostgresParser(), target_name="T")
    # 조언·검사 단계를 모두 조용히 만들고, ambiguous_column 하나만 필요에 따라 발동시킨다.
    orc._check_missing_columns = _empty
    orc._check_question_literals = lambda *_a, **_k: []
    orc._drop_real_values = lambda mutations, *_a, **_k: _passthrough(mutations)
    orc._check_empty_columns = _none
    orc._check_unrequested_columns = _none
    orc._check_redundant_joins = _empty
    orc._check_column_rationale = _none

    async def ambiguous(*_a, **_k):
        return [_Warn()] if advise else []

    orc._check_ambiguous_columns = ambiguous
    return orc


async def _passthrough(x):
    return x


def _run(coro):
    return asyncio.run(coro)


def test_조언_가드가_되돌린_sql을_후보로_기억한다() -> None:
    orc = _orchestrator(advise=True)
    fired: list[str] = []
    handlers, last_sql = orc._build_tool_handlers("q", "", "s", None, fired_log=fired)
    out = _run(handlers["generate_sql"]({"sql": SQL}))
    assert fired == ["ambiguous_column"]
    assert "조언" in out                 # 모델에게는 조언이 간다
    assert last_sql[0] is None           # 검증 통과 SQL 은 아직 없다
    assert last_sql[1] == SQL            # 그러나 되돌린 SQL 은 후보로 남는다


def test_같은_sql을_다시_내면_통과해_검증_sql이_된다() -> None:
    orc = _orchestrator(advise=True)
    handlers, last_sql = orc._build_tool_handlers("q", "", "s", None, fired_log=[])
    _run(handlers["generate_sql"]({"sql": SQL}))
    out = _run(handlers["generate_sql"]({"sql": SQL}))  # 조언은 질의당 한 번
    assert isinstance(out, dict) and out["sql"] == SQL
    assert last_sql[0] == SQL


def test_조언이_없으면_후보도_없다() -> None:
    orc = _orchestrator(advise=False)
    handlers, last_sql = orc._build_tool_handlers("q", "", "s", None, fired_log=[])
    _run(handlers["generate_sql"]({"sql": SQL}))
    assert last_sql == [SQL, None]


@pytest.mark.parametrize("bad", [
    # 실행 불가형(집계 혼용) 가드가 되돌린 SQL 은 후보로 두지 않는다 — 쓰면 실행에서 죽는다.
    "SELECT name, COUNT(*) FROM schools",
])
def test_실행_불가형_가드는_후보로_두지_않는다(bad: str) -> None:
    orc = _orchestrator(advise=False)
    handlers, last_sql = orc._build_tool_handlers("q", "", "s", None, fired_log=[])
    _run(handlers["generate_sql"]({"sql": bad}))
    assert last_sql == [None, None]
