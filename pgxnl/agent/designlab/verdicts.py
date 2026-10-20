"""LLM 의견(발견 항목 기반)에서 항목별 판정 블록을 떼어낸다.

"코드 항목과 LLM 의견이 일치하는지"를 화면에서 구분하려면(사용자 요청, 2026-10-02)
자유 서술만으로는 안 된다 — 서술을 다시 코드 항목에 짝짓는 건 추측이 된다. 그래서
프롬프트에서 항목에 F1..Fn 번호를 붙여 주고, 답 끝에 번호별 판정을 JSON 블록으로
받는다. 번호가 열쇠라 짝짓기는 정확하다.

모델이 블록을 빠뜨리거나 깨뜨릴 수 있다 — 그때는 판정 없이 서술만 돌려준다
(서술은 그대로 쓸 수 있으니 실패로 치지 않는다).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

VERDICTS = ("agree", "disagree", "unsure")

_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


@dataclass
class ParsedReview:
    text: str
    #: finding 인덱스(0부터) → {"verdict", "reason"}. 블록을 못 읽었으면 None.
    verdicts: dict[int, dict] | None = None
    additional: list[dict] = field(default_factory=list)


def finding_id(i: int) -> str:
    return f"F{i + 1}"


def parse_review(text: str, n_findings: int) -> ParsedReview:
    """마지막 ```json 블록을 판정으로 읽고, 화면용 서술에서는 그 블록을 지운다."""
    matches = list(_BLOCK_RE.finditer(text or ""))
    if not matches:
        return ParsedReview(text=text or "")
    m = matches[-1]
    clean = (text[: m.start()] + text[m.end():]).strip()
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return ParsedReview(text=clean)
    if not isinstance(data, dict):
        return ParsedReview(text=clean)

    verdicts: dict[int, dict] = {}
    for v in data.get("verdicts") or []:
        if not isinstance(v, dict):
            continue
        fid = str(v.get("id", "")).strip().upper()
        if not re.fullmatch(r"F\d+", fid):
            continue
        idx = int(fid[1:]) - 1
        verdict = str(v.get("verdict", "")).strip().lower()
        if not (0 <= idx < n_findings) or verdict not in VERDICTS:
            continue
        verdicts[idx] = {"verdict": verdict, "reason": str(v.get("reason") or "").strip()}

    additional = []
    for a in data.get("additional") or []:
        if isinstance(a, dict) and a.get("title"):
            additional.append({
                "title": str(a["title"]).strip(),
                "tables": [str(t) for t in a.get("tables") or []],
                "columns": [str(c) for c in a.get("columns") or []],
                "reason": str(a.get("reason") or "").strip(),
            })
    return ParsedReview(text=clean, verdicts=verdicts, additional=additional)
