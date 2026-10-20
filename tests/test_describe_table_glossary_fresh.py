"""describe_table 은 DDL만 캐시하고 용어집은 매번 새로 붙인다 (2026-10-07).

전엔 용어집까지 캐시돼(TTL 24시간) 용어집을 고쳐도 하루 동안 옛 내용이 나왔고, 평가 도중 캐시가
만료되며 측정 조건이 몰래 바뀌었다(run 375·376).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pgxnl.agent.tools.describe_table import describe_table


@dataclass
class _Entry:
    term: str
    column_name: str
    definition: str
    is_pii: bool = False


class _Cache:
    def __init__(self, data=None):
        self.data = data
        self.sets = 0

    async def get(self, _t, _k):
        return self.data

    async def set(self, _t, _k, data):
        self.data = data
        self.sets += 1


class _Glossary:
    def __init__(self, entries):
        self.entries = entries

    async def for_table(self, *_a):
        return self.entries


class _Conn:
    calls = 0

    async def describe_table(self, schema, table):
        _Conn.calls += 1

        class M:
            pass
        m = M()
        m.schema, m.name, m.comment, m.columns, m.foreign_keys = schema, table, None, [], []
        return m


def test_캐시에_옛_용어집이_있어도_지금_용어집을_붙인다() -> None:
    stale = {"schema": "s", "name": "cards", "comment": None, "columns": {"columns": [], "rows": []},
             "foreign_keys": [], "glossary": {"columns": ["term"], "rows": [["옛 항목"]]}}
    cache = _Cache(stale)
    out = asyncio.run(describe_table(_Conn(), cache, _Glossary([_Entry("새 항목", "name", "정의")]), "T", "s", "cards"))
    assert out["glossary"]["rows"] == [["새 항목", "name", "정의", False]]
    assert cache.sets == 0  # 캐시 히트 — DDL 은 다시 읽지 않는다


def test_캐시에는_용어집을_저장하지_않는다() -> None:
    cache = _Cache(None)
    out = asyncio.run(describe_table(_Conn(), cache, _Glossary([_Entry("a", "c", "d")]), "T", "s", "cards"))
    assert "glossary" in out
    assert "glossary" not in cache.data
    assert list(out)[-1] == "glossary"  # 출력 키 순서는 예전과 같다(용어집이 마지막)


def test_용어집_저장소가_없으면_키가_없다() -> None:
    out = asyncio.run(describe_table(_Conn(), _Cache(None), None, "T", "s", "cards"))
    assert "glossary" not in out
