from pgxnl.agent.designlab.verdicts import parse_review

BODY = "의견 본문입니다.\n\n"


def test_parses_last_json_block_and_strips_it():
    text = BODY + '```json\n{"verdicts": [{"id": "F1", "verdict": "agree", "reason": "맞음"},' \
        ' {"id": "f2", "verdict": "Disagree", "reason": "아님"}], "additional": [{"title": "누락", "tables": ["t"]}]}\n```'
    r = parse_review(text, 2)
    assert r.text == "의견 본문입니다."
    assert r.verdicts == {0: {"verdict": "agree", "reason": "맞음"}, 1: {"verdict": "disagree", "reason": "아님"}}
    assert r.additional == [{"title": "누락", "tables": ["t"], "columns": [], "reason": ""}]


def test_drops_out_of_range_ids_and_unknown_verdicts():
    text = '```json\n{"verdicts": [{"id": "F3", "verdict": "agree"}, {"id": "F1", "verdict": "maybe"},' \
        ' {"id": "X", "verdict": "agree"}]}\n```'
    r = parse_review(text, 2)
    assert r.verdicts == {}


def test_no_block_means_no_verdicts_but_text_kept():
    r = parse_review(BODY, 2)
    assert r.verdicts is None and r.text == BODY


def test_broken_json_keeps_text_without_block():
    r = parse_review(BODY + "```json\n{\"verdicts\": [\n```", 2)
    assert r.verdicts is None and r.text == "의견 본문입니다."


def test_only_last_block_is_verdicts():
    text = '예시:\n```json\n{"verdicts": []}\n```\n본문\n```json\n{"verdicts": [{"id": "F1", "verdict": "unsure"}]}\n```'
    r = parse_review(text, 1)
    assert r.verdicts == {0: {"verdict": "unsure", "reason": ""}}
    assert '{"verdicts": []}' in r.text
