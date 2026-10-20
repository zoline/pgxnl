"""정규형 위반 후보를 **이름만 보고** 뽑아내는 순수 함수들.

값 검증(데이터 조회)은 `analyzer`가 한다 — 여기서는 후보만 만든다. 나눈 이유는
후보 추출이 순수 함수라 테스트가 싸고, 데이터 조회는 비싸서 후보 수를 먼저 줄여야
하기 때문이다. **함수 종속을 전수 탐색하면 컬럼 수에 지수적이다**(BIRD `schools`만
49개 컬럼) — 이름 패턴으로 후보를 좁히는 것이 이 모듈의 존재 이유다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: 반복 그룹 후보: 이름 끝의 일련번호 (`admemail1`, `admemail2`, ...).
_REPEATING_SUFFIX = re.compile(r"^(?P<base>.*?[^\d_])[_\s]?(?P<n>\d{1,2})$")

#: 코드->이름 이행 종속 후보: 같은 어간에 붙는 접미사 쌍.
#: 예) soc/soctype, edopscode/edopsname, "County Code"/"County Name"
_CODE_SUFFIXES = ("code", "cd", "id", "")
_NAME_SUFFIXES = ("type", "name", "desc", "description", "label")

#: 이름이 같아도 개념이 같다고 볼 수 없는 컬럼. 테이블 간 중복 판정에서 제외한다.
#:
#: **시각/일시**: 각 테이블의 행이 언제 생겼는지를 뜻하는 경우가 많다 — `financial`의
#: 세 테이블에 있는 `date`는 계좌개설일/거래일/대출일이고, `formula_1`의 네 테이블에
#: 있는 `time`은 경기 시작 시각/완주 기록/랩 타임/피트인 시각이다. 사본이 아니다.
#:
#: **구조적 이름**: `id`, `code`, `type` 등은 모든 테이블이 자기 것을 갖는다 —
#: `card_games`의 6개 테이블에 있는 `id`가 중복으로 보고됐다.
#:
#: 이름만으로 개념을 묶는 방식의 근본 한계라, 데이터 검증(불일치율)만으로는 거를 수
#: 없다. 값이 100% 달라도 "사본인데 심하게 갈렸다"와 구분되지 않기 때문이다.
GENERIC_COLUMNS = frozenset({
    "date", "time", "datetime", "timestamp", "createdat", "updatedat", "modifiedat",
    "created", "updated", "modified", "lastupdate", "lastupdated", "insertedat",
    "id", "code", "key", "seq", "no", "num", "type", "status", "value", "text",
    "description", "comment", "note", "url", "flag", "count", "total", "amount",
})

#: 개념 이름을 정규화할 때 떼어내는 접미사 — `School Name`/`sname`/`school`이
#: 같은 개념임을 알아보려면 표기 차이를 걷어내야 한다.
_CONCEPT_NOISE = re.compile(r"(?:_|\s)*(?:name|nm)$", re.IGNORECASE)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass(frozen=True)
class RepeatingGroupCandidate:
    """1NF 위반 후보 — 같은 속성이 번호를 달고 여러 컬럼으로 펼쳐진 경우."""

    table: str
    base: str
    columns: list[str]


@dataclass(frozen=True)
class CodeNameCandidate:
    """3NF(이행 종속) 후보 — 같은 테이블 안의 `코드 -> 이름` 쌍."""

    table: str
    code_column: str
    name_column: str


@dataclass(frozen=True)
class DuplicateConceptCandidate:
    """테이블 간 중복 후보 — 같은 개념이 여러 테이블에 사본으로 존재."""

    concept: str
    #: (테이블, 컬럼) 목록. 2개 이상일 때만 후보가 된다.
    columns: list[tuple[str, str]]


def find_repeating_groups(
    columns_by_table: dict[str, list[str]], *, min_size: int = 2
) -> list[RepeatingGroupCandidate]:
    """`admemail1/2/3`처럼 번호가 붙은 컬럼 묶음을 찾는다.

    번호가 **의미의 일부**인 경우(`enrollment12` = 12학년)를 반복 그룹으로 오인하면
    안 되므로, 같은 어간이 `min_size`개 이상 연속으로 있을 때만 후보로 본다 —
    12학년 컬럼은 하나뿐이라 걸리지 않는다.
    """
    out: list[RepeatingGroupCandidate] = []
    for table, columns in columns_by_table.items():
        groups: dict[str, list[str]] = {}
        for col in columns:
            m = _REPEATING_SUFFIX.match(col)
            if m:
                groups.setdefault(m.group("base").lower(), []).append(col)
        out += [
            RepeatingGroupCandidate(table=table, base=base, columns=sorted(cols))
            for base, cols in groups.items()
            if len(cols) >= min_size
        ]
    return sorted(out, key=lambda r: (r.table, r.base))


def find_code_name_pairs(columns_by_table: dict[str, list[str]]) -> list[CodeNameCandidate]:
    """같은 테이블 안에서 `soc`/`soctype`, `County Code`/`County Name` 같은 쌍을 찾는다.

    이런 쌍은 코드가 이름을 함수적으로 결정하므로(같은 코드 -> 항상 같은 이름) 3NF
    이행 종속이다. **여기서는 이름만 보고 후보를 만든다** — 실제로 함수 종속이
    성립하는지는 데이터로 확인해야 한다(`analyzer`가 한다).
    """
    out: list[CodeNameCandidate] = []
    for table, columns in columns_by_table.items():
        by_norm = {_norm(c): c for c in columns}
        for col in columns:
            n = _norm(col)
            for code_suffix in _CODE_SUFFIXES:
                if code_suffix and not n.endswith(code_suffix):
                    continue
                stem = n[: len(n) - len(code_suffix)] if code_suffix else n
                if not stem:
                    continue
                for name_suffix in _NAME_SUFFIXES:
                    other = by_norm.get(stem + name_suffix)
                    if other and other != col:
                        out.append(CodeNameCandidate(table, col, other))
                break  # 가장 긴 코드 접미사 하나만 사용
    # (table, code, name) 중복 제거 — 접미사 조합이 겹칠 수 있다
    seen, unique = set(), []
    for c in out:
        key = (c.table, _norm(c.code_column), _norm(c.name_column))
        if key not in seen and key[1] != key[2]:
            seen.add(key)
            unique.append(c)
    return sorted(unique, key=lambda c: (c.table, c.code_column))


def find_duplicate_concepts(
    columns_by_table: dict[str, list[str]], *, aliases: dict[str, str] | None = None
) -> list[DuplicateConceptCandidate]:
    """여러 테이블에 흩어진 같은 개념의 컬럼을 묶는다.

    표기가 제각각이라(`school` / `School Name` / `sname`) 정규화만으로는 부족하다.
    `aliases`로 "이 컬럼명은 이 개념" 매핑을 넘길 수 있게 열어둔다 — 자동 추론에는
    한계가 있고, 잘못 묶으면 무관한 컬럼을 중복이라고 경고하게 된다.
    """
    aliases = {_norm(k): v for k, v in (aliases or {}).items()}
    concepts: dict[str, list[tuple[str, str]]] = {}
    for table, columns in columns_by_table.items():
        for col in columns:
            n = _norm(col)
            if n in GENERIC_COLUMNS:
                continue  # 이름이 같아도 개념이 같지 않다 (위 GENERIC_COLUMNS 참고)
            concept = aliases.get(n) or _CONCEPT_NOISE.sub("", col).strip().lower()
            concept = re.sub(r"[^a-z0-9]", "", concept)
            if not concept or concept in GENERIC_COLUMNS:
                continue
            concepts.setdefault(concept, []).append((table, col))
    return [
        DuplicateConceptCandidate(concept=c, columns=sorted(cols))
        for c, cols in sorted(concepts.items())
        if len({t for t, _ in cols}) > 1
    ]
