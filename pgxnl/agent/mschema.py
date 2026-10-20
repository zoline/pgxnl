"""M-Schema 직렬화. design 문서 §3.1(스키마 직렬화)/§5.4 참고.

경량 표현(light_doc, 임베딩 검색 전용)과 전체 M-Schema(값 예시·PK/FK 포함, SQL 생성
프롬프트 조립용)를 분리하는 것이 핵심이다 — 값 예시가 섞인 텍스트를 그대로 임베딩하면
벡터가 "테이블의 의미"보다 "값의 표면적 분포"에 쏠려 검색 정밀도가 떨어진다.
"""
from __future__ import annotations

from pgxnl.connectors.base import TableMeta

_MAX_EXAMPLE_VALUES = 3
_MAX_EXAMPLE_VALUE_LEN = 50
# 컬럼이 매우 많은 테이블(예: BIRD european_football_2.Match, 컬럼 100개+)을 전부
# 나열하면 임베딩 모델의 최대 시퀀스 길이를 넘길 수 있다 — 실제로 IBM
# granite-embedding-278m-multilingual(512 토큰 제한)에서 재구축이 통째로 실패하는
# 걸 겪었다. 검색용 경량 표현은 "테이블이 대략 뭘 다루는지" 가늠하는 용도라 전체
# 컬럼을 다 나열할 필요가 없어, 앞쪽 컬럼만 포함해 캡핑한다.
_MAX_LIGHT_DOC_COLUMNS = 40


def to_light_doc(table: TableMeta) -> str:
    """임베딩 검색 전용 경량 표현. 값 예시를 넣지 않는다."""
    col_names = [c.name for c in table.columns]
    shown = col_names[:_MAX_LIGHT_DOC_COLUMNS]
    remaining = len(col_names) - len(shown)
    col_text = ", ".join(shown) + (f", ... (+{remaining}개 컬럼 생략)" if remaining > 0 else "")
    comment = f" — {table.comment}" if table.comment else ""
    return f"{table.schema}.{table.name}{comment} ({col_text})"


def sibling_joins(tables: list[TableMeta]) -> dict[str, list[tuple[str, str, str]]]:
    """`{테이블: [(내 컬럼, 상대 테이블, 상대 컬럼), ...]}` — 직접 조인 가능한 형제 쌍.

    **같은 부모 컬럼을 참조하는 두 테이블은 자기 FK 컬럼끼리 직접 조인할 수 있다.**
    선언된 FK만 보여주면 모델은 부모를 경유하는 경로밖에 알지 못해, 조건에 전혀
    기여하지 않는 테이블을 끌어들인다.

    실측(BIRD 443): `frpm.cdscode -> schools.cdscode`와 `satscores.cds -> schools.cdscode`만
    보여주니 모델이 `schools`를 기준 테이블로 세우고 둘을 매달았다. 그런데
    `frpm.cdscode = satscores.cds` 직접 조인이 **행 집합까지 동일**하다(1,782행, 양방향
    차집합 0, 고아 행 0). gold는 직접 조인을 쓴다.

    부모 쪽은 넣지 않는다 — 부모는 이미 각 자식의 `[Foreign Keys]`에 나와 있다.
    """
    by_parent: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for t in tables:
        for local_col, ref_table, ref_col in t.foreign_keys:
            key = (ref_table.split(".")[-1].lower(), ref_col.lower())
            by_parent.setdefault(key, []).append((t.name, local_col))

    out: dict[str, list[tuple[str, str, str]]] = {}
    for members in by_parent.values():
        if len(members) < 2:
            continue
        for name, local_col in members:
            for other, other_col in members:
                if other == name:
                    continue
                out.setdefault(name, []).append((local_col, other, other_col))
    return out


def to_mschema(
    table: TableMeta,
    canonical: dict[str, str] | None = None,
    siblings: list[tuple[str, str, str]] | None = None,
) -> str:
    """SQL 생성 프롬프트 조립용 전체 M-Schema. 값 예시는 최대 3개, 각 50자로 제한.

    `canonical`은 `{컬럼명: "schema.table.column 의 사본 (N% 불일치)"}` 형태로, 같은
    개념의 사본이 여러 테이블에 있고 **값이 갈릴 때** 어느 쪽이 원본인지 표시한다.

    이 정보를 용어집이 아니라 **컬럼 줄에** 두는 이유(실측 2026-09-04): 용어집 항목을
    추가하면 그 테이블 블록이 커지고, **모델은 가장 큰 블록의 테이블을 고른다.**
    "schools가 정본"이라고 알려주려고 frpm에 용어집을 달면 오히려 frpm 블록이 커져
    frpm으로 끌어당기는 역효과가 난다. 컬럼 줄에 붙이면 30자 남짓이라 균형을 안 깬다.
    PK 태그를 `(cdscode, text, PK)`로 붙이는 것과 같은 자리다.
    """
    canonical = canonical or {}
    lines = [f"# Table: {table.schema}.{table.name}" + (f", {table.comment}" if table.comment else "")]
    lines.append("[")
    for c in table.columns:
        examples = _format_examples(c.example_values)
        pk = ", PK" if c.is_primary_key else ""
        comment = f", {c.comment}" if c.comment else ""
        canon = f", {canonical[c.name]}" if c.name in canonical else ""
        lines.append(f"  ({c.name}, {c.data_type}{comment}{pk}{canon}{examples}),")
    lines.append("]")
    # FK 와 승인·형제 조인을 한 섹션으로(2026-10-14 사용자). 따로 두면 [Foreign Keys] 가 먼저 나와 모델이 FK 경로를
    # 우선했고(codebase_community 311), 기호만 바꾼 `->` 는 뜻이 안 드러나 california 441 이 흔들렸다 —
    # 줄마다 관계 종류를 붙여 대등하게 보이게 한다.
    # M-Schema 원형(XiYan-SQL m_schema.py)대로 `【Foreign keys】` + `a.x=b.y` (2026-10-15 사용자).
    # 그전엔 `[Foreign Keys]`·`a -> b` 로 원형과 달랐고, 10/14 에 `[JOIN 경로]` 한 섹션·`# FK` 표시도 시험했다.
    if table.foreign_keys:
        lines.append("【Foreign keys】")
        lines.extend(f"{table.name}.{lc}={rt}.{rc}" for lc, rt, rc in table.foreign_keys)
    # 원형에 없는 확장: 같은 부모를 참조하는 테이블끼리, 또는 승인된 조인 — 부모를 거치지 않고 바로 조인(§sibling_joins).
    if siblings:
        lines.append("【Join paths】")
        lines.extend(f"{table.name}.{lc}={ot}.{oc}" for lc, ot, oc in siblings)
    return "\n".join(lines)


def _format_examples(values: list | None) -> str:
    if not values:
        return ""
    seen: list[str] = []
    for v in values:
        text = str(v)[:_MAX_EXAMPLE_VALUE_LEN]
        if text not in seen:
            seen.append(text)
        if len(seen) >= _MAX_EXAMPLE_VALUES:
            break
    return f", example: [{', '.join(seen)}]"
