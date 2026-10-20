"""조인 그래프의 스키마 분리(2026-10-07) — schema_name 열 + 맨 테이블 이름."""
from __future__ import annotations

from pgxnl.agent.discovery.graph import JoinEdge, edge_key, split_schema


def test_split_schema() -> None:
    assert split_schema("card_games.cards") == ("card_games", "cards")
    assert split_schema('"Card_Games"."Sets"') == ("card_games", "sets")
    assert split_schema("cards") == ("", "cards")


def test_한정_이름에서_스키마를_뗀다() -> None:
    assert edge_key("", "card_games.sets", "code", "card_games.cards", "setCode") == (
        "card_games", "cards", "setcode", "sets", "code")


def test_인자_스키마가_맨_이름에_붙는다() -> None:
    assert edge_key("card_games", "cards", "setcode", "sets", "code") == (
        "card_games", "cards", "setcode", "sets", "code")


def test_방향이_달라도_같은_키() -> None:
    assert edge_key("s", "a", "x", "b", "y") == edge_key("s", "b", "y", "a", "x")


def test_한정과_맨_이름이_같은_키() -> None:
    # 전엔 `frpm` 과 `california_schools.frpm` 이 별개 행이 됐다.
    assert edge_key("california_schools", "frpm", "cdscode", "satscores", "cds") == \
        edge_key("", "california_schools.frpm", "cdscode", "california_schools.satscores", "cds")


def test_스키마를_못_정하면_미상() -> None:
    assert edge_key("", "cards", "setcode", "sets", "code")[0] == ""


def test_스키마를_넘나들면_한정_이름을_남기고_미상() -> None:
    k = edge_key("", "a.t1", "x", "b.t2", "y")
    assert k[0] == ""
    assert {k[1], k[3]} == {"a.t1", "b.t2"}


def test_qualified_표시() -> None:
    e = JoinEdge(1, "cards", "setcode", "sets", "code", "manual", 1.0, None, True, "card_games")
    assert e.qualified(e.table_a) == "card_games.cards"
    assert JoinEdge(2, "t", "a", "u", "b", "manual", 1.0, None, True).qualified("t") == "t"
