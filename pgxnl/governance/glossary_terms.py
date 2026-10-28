"""용어집 항목의 텍스트를 다루는 순수 함수들 — 관련성 판정, 정규화, 진단.

`GlossaryStore`(DB 접근)와 orchestrator(프롬프트 조립) 어느 쪽에도 속하지 않는다.
등록 시점(관리 API)과 사용 시점(schema_context 조립)이 **같은 규칙**을 봐야 하기
때문에 한 곳에 모았다 — 규칙이 갈라지면 "등록은 됐는데 어떤 질문에도 안 실리는"
항목이 조용히 생긴다.

용어집 매칭은 ADR-0003에 따라 임베딩 유사도가 아니라 정확 매칭이다. 여기에도
새 검색 인프라를 붙이지 않는다.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

_CODE_VALUE_PATTERN = re.compile(r"([^\s,=]+)\s*=\s*([^,\n]+)")
_VALUE_LIST_PATTERN = re.compile(r"(?P<label>values|값)\s*:\s*(?P<body>[^\n]+)", re.IGNORECASE)
_CODE_PREFIX_PATTERN = re.compile(r"^['\"]?[A-Za-z0-9]{1,8}['\"]?\s*=\s*")
_WORD_PATTERN = re.compile(r"[a-z0-9]+")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+|[가-힣]+")

#: 값 라벨로 인정하는 최소 길이. 두세 글자는 우연히 일치하기 쉬워 신호로 쓰지 않는다.
MIN_VALUE_LENGTH = 4
#: 이보다 긴 정의문은 서술이 섞였다고 보고 경고한다(실측: 단문화 전 평균 181자).
MAX_DEFINITION_LENGTH = 200


def mentions(haystack_lower: str, phrase: str) -> bool:
    """phrase의 모든 낱말이 haystack에 낱말 경계로 등장하는지. 순서는 보지 않는다.

    낱말 경계를 쓰는 이유: 'DOC' 같은 3글자 약어가 'document'/'doctor' 안에 부분
    일치하면 무관한 항목이 실린다. 순서를 안 보는 이유: 등록어 'average score in
    writing'을 질문이 'average writing score'로 쓰는 것까지 잡아야 하기 때문이다.

    한글 낱말은 앞 경계만 본다 — 조사가 붙어("매출을", "매출이") 뒤 경계가 없다.
    예전엔 [a-z0-9]만 낱말로 쳐서 한글 등록어는 어떤 질문에도 걸리지 않았다(2026-10-28,
    Northwind). "총매출"처럼 앞에 붙은 합성어는 놓치지만, 과소 포함이 안전하다(is_relevant).
    """
    tokens = _TOKEN_PATTERN.findall(phrase.lower())
    if not tokens:
        return False
    return all(re.search(_token_regex(t), haystack_lower) for t in tokens)


def _token_regex(token: str) -> str:
    if "가" <= token[0] <= "힣":
        return rf"(?<![가-힣]){re.escape(token)}"
    return rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])"


def aliases(term: str | None, column_name: str | None) -> list[str]:
    """term/column_name을 쉼표로 나눈 각 표현이 별칭이다.

    등록어가 컬럼명 그대로(`GSoffered`)면 자연어 질문에 절대 안 걸리므로,
    `GSoffered, grade span offered`처럼 자연어 표현을 덧붙이게 하려는 관례다.
    """
    return [a.strip() for whole in (term or "", column_name or "") for a in whole.split(",") if a.strip()]


def definition_values(definition: str) -> list[str]:
    """정의문에서 "질문에 그대로 나올 법한 값 라벨"을 뽑는다.

    두 표기를 지원한다 — `Values: Locally funded, Directly funded` 같은 코드 없는
    나열과, `31=State Special Schools` 같은 코드=값 표기. 전자를 지원하는 이유는
    실측(seq 447) 때문이다: FundingType 정의가 값만 나열하는 형태라 코드=값 쌍이
    하나도 없었고, 질문의 "locally funded"를 아무 신호도 잡지 못했다.

    코드 자체(`31`, `54`)는 신호로 쓰지 않는다 — 두 자리 숫자는 너무 약해서 seq 452의
    날짜 `12/31/1980`이 DOC의 코드 `'31'`에 걸렸다. 값을 코드로 지칭하는 질문은
    evidence에서 `DOC = 31`처럼 약어를 함께 쓰므로 별칭 신호로 이미 잡힌다.

    나열은 쉼표로만 끊는다. `/`로도 끊었더니 `98=Regional Occupational Center/Program`이
    'Program' 한 단어로 쪼개져 seq 465의 "magnet program"에 걸렸다 — 값 라벨의 일부만
    떼어내면 그건 더 이상 그 값을 가리키지 않는다.
    """
    values: list[str] = []
    for match in _VALUE_LIST_PATTERN.finditer(definition):
        values += match.group("body").split(",")
    if not values:  # "Values:" 관례를 안 따른 항목 — 코드=값 쌍에서 직접 뽑는다
        values = [label for _, label in _CODE_VALUE_PATTERN.findall(definition)]
    stripped = (_CODE_PREFIX_PATTERN.sub("", v.strip(" .\"'")) for v in values)
    return [v for v in stripped if len(v) >= MIN_VALUE_LENGTH]


def is_relevant(question: str, term: str | None, column_name: str | None, definition: str) -> bool:
    """이 용어집 항목이 이 질문에 실릴 만한지 판정한다(§5.11).

    **기본값은 "제외"다.** 예전 구현은 정의문에 "코드=값" 나열이 없으면 무조건
    포함시켰는데, 서술형으로 길게 쓴 항목일수록 코드=값 쌍이 없어서 필터를 그냥
    빠져나갔다 — 실측(2026-09-03) 결과 13개 중 10개가 30문항 전부에서 통과해
    schema_context의 43%(1,761자)가 매번 무관한 용어집이었다. 필터가 사실상
    없었던 셈이다.

    용어집은 보조 컴포넌트이므로(설계 원칙 1) 빠져도 ReAct가 describe_table로
    스키마를 볼 수 있다 — 과잉 포함보다 과소 포함이 안전하다.
    """
    q = question.lower()
    if any(mentions(q, a) for a in aliases(term, column_name)):
        return True
    return any(mentions(q, v) for v in definition_values(definition))


def normalize_definition(definition: str) -> str:
    """등록된 정의문을 필터가 읽을 수 있는 표준형으로 다듬는다 — **기계적인 것만**.

    서술을 값 나열로 바꾸는 건 뜻을 바꾸는 일이라 사람이 해야 한다. 여기서는
    되돌릴 수 있는 표기 차이만 흡수한다:

    - 공백/줄바꿈 정리
    - `값:` -> `Values:` (필터는 둘 다 읽지만 표기를 하나로 모아 진단을 단순하게)
    - 값 나열의 구분자 통일: 쉼표가 없고 ` / `로만 나뉜 나열은 쉼표로 바꾼다.
      실제로 FundingType이 `"A" / "B" / "C"` 형태로 등록돼 있었다. 쉼표가 이미
      있으면 건드리지 않는다 — `Center/Program`처럼 값 **안에** 든 `/`를
      쪼개면 안 되기 때문이다.
    - 값의 겉따옴표 제거
    """
    text = re.sub(r"\s+", " ", definition).strip()
    text = re.sub(r"(?:^|(?<=[\s.—-]))값\s*:", "Values:", text)

    def _fix_list(match: re.Match[str]) -> str:
        # 라벨은 원문 표기를 그대로 둔다 — 소문자 `values:`를 대문자로 고치면
        # "the text values:" 같은 문장 중간의 낱말까지 `Values:`로 바뀌어 문장이 망가진다.
        body = match.group("body")
        if "," not in body and " / " in body:
            body = ", ".join(part.strip() for part in body.split(" / "))
        body = re.sub(r"['\"]([^'\"]+)['\"]", r"\1", body)
        return f"{match.group('label')}: {body}"

    return _VALUE_LIST_PATTERN.sub(_fix_list, text)


@dataclass
class EntryDiagnosis:
    """이 항목이 언제 프롬프트에 실리는지를 관리자에게 보여주기 위한 진단 결과."""

    aliases: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_dead(self) -> bool:
        """어떤 질문에도 실릴 수 없는 항목."""
        return not self.aliases and not self.values


def diagnose(term: str | None, column_name: str | None, definition: str) -> EntryDiagnosis:
    """등록/수정 시점에 "이 항목이 실제로 쓰이긴 하는가"를 알려준다.

    필터를 "기본 제외"로 뒤집으면서 생긴 새로운 실패 모드를 막기 위한 것이다:
    예전에는 서술형으로 아무렇게나 등록해도 무조건 실렸지만, 이제는 신호가 없으면
    **조용히 한 번도 안 실린다.** 등록은 성공했는데 아무 효과가 없는 상태가 제일
    나쁘므로 그 자리에서 경고한다. 등록 자체를 막지는 않는다 — 관리자가 의도적으로
    좁게 등록할 수도 있고, 판정을 틀리게 하느니 알려주고 맡기는 게 낫다.
    """
    alias_list = aliases(term, column_name)
    values = definition_values(definition)
    warnings: list[str] = []

    if not alias_list and not values:
        warnings.append(
            "이 항목은 어떤 질문에도 실리지 않습니다 — 등록어나 컬럼명이 질문에 그대로 "
            "나오거나, 정의에 'Values: A, B, C' 형태로 값을 나열해야 합니다."
        )
    elif not values:
        warnings.append(
            "값 나열이 없어 등록어/컬럼명이 질문에 그대로 나올 때만 실립니다. "
            "값으로도 걸리게 하려면 정의를 'Values: A, B, C' 형태로 쓰세요."
        )

    if alias_list and all(_WORD_PATTERN.fullmatch(a.lower()) for a in alias_list):
        warnings.append(
            "등록어가 한 낱말뿐입니다 — 자연어 질문에 걸리려면 "
            "'GSoffered, grade span offered'처럼 자연어 표현을 쉼표로 덧붙이세요."
        )

    if len(definition) > MAX_DEFINITION_LENGTH:
        warnings.append(
            f"정의가 {len(definition)}자로 깁니다(권장 {MAX_DEFINITION_LENGTH}자 이하). "
            "예제와 서술을 빼고 값 나열로 줄이면 프롬프트 토큰이 줄고 필터도 정확해집니다."
        )

    return EntryDiagnosis(aliases=alias_list, values=values, warnings=warnings)


#: 대상 DB 카탈로그를 읽는 콜백. (schema, table) -> 컬럼명 집합.
#: 테이블이 없으면 None을 돌려준다. 조회 자체가 실패하면 예외를 던져도 된다 —
#: 호출자가 "판단 불가"로 처리한다.
CatalogLookup = Callable[[str, str], Awaitable[set[str] | None]]


async def verify_against_catalog(
    lookup: CatalogLookup,
    *,
    target_name: str | None,
    schema_name: str | None,
    table_name: str | None,
    column_name: str | None,
    known_tables: set[str] | None = None,
) -> list[str]:
    """등록하려는 테이블/컬럼이 대상 DB에 실제로 있는지 확인하고 경고를 돌려준다.

    `diagnose()`는 순수 함수라 텍스트만 본다 — 그래서 `table_name`이 `shcools`(오타)여도
    통과시켰고, 그 항목은 `for_table()`이 `table_name='schools'`로 조회하므로 **어떤
    질문에도 실리지 않는 상태로 등록됐다**(실측 2026-09-03). 등록 시점 진단의 목적이
    정확히 그 상태를 막는 것인데 놓친 구멍이다.

    **검사하지 않는 경우** — NULL은 "제한 없음"을 뜻하는 관례라 특정 DB로 판정하면 안 된다:

    - `target_name`이 NULL: 모든 대상 DB에 적용되는 전역 항목
    - `schema_name`이 NULL: 스키마 무관하게 적용
    - `table_name`이 NULL: 테이블에 매이지 않은 항목

    조회가 실패하면 빈 목록을 돌려준다 — 대상 DB에 못 붙는 것은 "판단 불가"이지
    등록을 막을 사유가 아니다(`SqlValidator._bind_columns`와 같은 원칙).
    """
    if not target_name or not schema_name or not table_name:
        return []
    try:
        columns = await lookup(schema_name, table_name)
    except Exception:  # noqa: BLE001 — 조회 실패는 판단 불가
        return []

    if columns is None:
        hint = ""
        if known_tables:
            close = difflib.get_close_matches(table_name, sorted(known_tables), n=1, cutoff=0.6)
            hint = f" '{close[0]}'을(를) 의도하셨나요?" if close else ""
        return [f"'{schema_name}' 스키마에 '{table_name}' 테이블이 없습니다 — "
                f"이 항목은 어떤 질문에도 실리지 않습니다.{hint}"]

    if column_name and column_name.lower() not in {c.lower() for c in columns}:
        close = difflib.get_close_matches(column_name, sorted(columns), n=1, cutoff=0.6)
        hint = f" '{close[0]}'을(를) 의도하셨나요?" if close else ""
        return [f"'{table_name}' 테이블에 '{column_name}' 컬럼이 없습니다.{hint}"]
    return []
