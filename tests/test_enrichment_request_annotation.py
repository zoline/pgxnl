"""요구 구분 표시 — 요구가 여럿이고 선택 표지(if there is any)가 있을 때만 붙인다 (2026-10-13)."""
from __future__ import annotations

from pgxnl.agent.enrichment import QuestionEnricher

E = QuestionEnricher(None, None, enabled=True)


def test_397_두_요구와_선택_표시() -> None:
    q = "List all the frame styles and cards Allen Williams worked on and find any banned cards if there are any."
    text, reason = E._annotate_requests(q)
    assert reason and text.startswith(q)  # 원문은 그대로
    assert "1. List all the frame styles and cards Allen Williams worked on" in text
    assert "2. find any banned cards if there are any. (선택" in text


def test_446_세_요구() -> None:
    q = ("What is the average score in writing for the schools that were opened after 1991 or closed before 2000? "
         "List the school names along with the score. Also, list the communication number of the schools if there is any.")
    text, reason = E._annotate_requests(q)
    assert "요구 3개" in reason
    assert text.count("(선택") == 1 and "3. Also, list the communication number" in text


def test_선택_표지가_없으면_그대로() -> None:
    for q in ["Name the card and artist with the most ruling information. Also state if the card is a promotional printing.",
              "What is the percentage of Story Spotlight cards that do not have a text box? List them by their ID.",
              "List the names of schools with more than 30 students."]:
        assert E._annotate_requests(q) == (q, None)


def test_요구가_하나면_그대로() -> None:
    q = "List the cards with a foreign name if there is any."
    assert E._annotate_requests(q) == (q, None)
