"""Orchestrator. design 문서 §4(질의 처리 흐름), §5.1 참고.

모든 하위 컴포넌트를 조립하고 analyze()로 질문 보강 -> 캐시 조회 -> 스키마 링킹 ->
문서 지식 레이어 -> ReAct 루프 -> Canonicalization -> 검증 -> 실행 -> 캐시 저장까지
전체 흐름을 수행한다.

초기화 순서 주의: SchemaExplorer 역할을 하는 PgConnector를 먼저 만든 뒤
SchemaVectorIndex를 생성해야 한다. 여기서는 두 컴포넌트가 서로 직접 참조하지 않도록
설계해 이 문제를 피했다(원본 pgxrsa의 역참조 주입 방식과 달리 도구 함수에 둘 다
파라미터로 전달).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pgxnl.agent.canonicalize import (
    build_column_owners, canonicalize_sql_verbose, load_rules_from_store,
)
from pgxnl.agent.enrichment import QuestionEnricher
from pgxnl.agent.planner import ReactPlanner
from pgxnl.agent.stats.base import StatsAdapter
from pgxnl.agent.stats_guard import check_ambiguous_columns, check_empty_columns
from pgxnl.agent.stats_guard import parse_rule as parse_stats_guard_rule
from pgxnl.agent.tools import (
    collect_stats,
    describe_table,
    generate_sql,
    sample_data,
    search_tables,
)
from pgxnl.agent.validation import Decision, SqlValidator, record_audit_log, window_misuse_clause
from pgxnl.cache.schema import SchemaCache
from pgxnl.cache.schema_vector import SchemaVectorIndex
from pgxnl.cache.semantic import SemanticCache
from pgxnl.connectors.postgresql import PgConnector
from pgxnl.agent.alias_scope import find_unresolved_aliases
from pgxnl.agent.canonical_rewrite import (
    load_examples as load_rewrite_examples,
    rewrite_sql,
)
from pgxnl.agent.scalar_subquery import find_multicolumn_scalar_subqueries
from pgxnl.agent.aggregate_mix import find_aggregate_mix
from pgxnl.agent.missing_column import find_missing_columns
from pgxnl.agent.redundant_join import find_redundant_joins
from pgxnl.agent.column_rationale import (
    RATIONALE_PROMPT,
    RATIONALE_TIMEOUT_SECONDS,
    find_unsupported,
    parse_rationale,
)
from pgxnl.governance.glossary import GlossaryEntry, GlossaryStore
from pgxnl.governance.glossary_terms import is_relevant
from pgxnl.governance.rules import SqlRuleStore
from pgxnl.llm.base import BaseLLMClient
from pgxnl.parsing.base import SqlParser
from pgxnl.settings import Settings

logger = logging.getLogger(__name__)

OnStep = Callable[[str], Awaitable[None]]

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_tables",
        "description": "키워드로 관련 테이블을 검색합니다.",
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"],
        },
    },
    {
        "name": "describe_table",
        "description": "테이블의 컬럼 구조와 업무 용어 정의를 조회합니다.",
        "input_schema": {
            "type": "object",
            "properties": {"schema": {"type": "string"}, "table": {"type": "string"}},
            "required": ["schema", "table"],
        },
    },
    {
        "name": "sample_data",
        "description": "테이블의 실제 데이터 샘플을 조회합니다 (코드값·날짜 형식 파악용).",
        "input_schema": {
            "type": "object",
            "properties": {"schema": {"type": "string"}, "table": {"type": "string"}},
            "required": ["schema", "table"],
        },
    },
    {
        "name": "collect_stats",
        "description": "컬럼의 고유값·null 비율·최빈값 통계를 조회합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "schema": {"type": "string"}, "table": {"type": "string"}, "column": {"type": "string"},
            },
            "required": ["schema", "table", "column"],
        },
    },
    {
        "name": "generate_sql",
        "description": (
            "지금까지 도구 호출로 확인한 실제 테이블/컬럼명을 바탕으로 질문에 답하는 단일 SELECT 문을 "
            "sql 인자에 담아 호출하세요. describe_table로 확인하지 않은 테이블/컬럼명을 추측해서 쓰지 마세요. "
            "finalize 이전에 반드시 호출해야 합니다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "실행할 단일 SELECT 문"}},
        },
    },
    {
        "name": "finalize",
        "description": "분석을 종료하고 최종 자연어 답변을 반환합니다.",
        "input_schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
    },
]


#: 디버그 때만 도구 호출에 붙이는 이유 칸(2026-10-15 사용자). thinking 을 끈 모델은 이유를 말하지 않고 도구만
#: 호출해 디버그 화면에 판단 근거가 없었다. **주의:** 이유를 쓰게 하면 모델 판단이 달라질 수 있어, 디버그 실행의
#: SQL 이 평소·평가 실행과 다를 수 있다.
_REASON_PROP = {
    "type": "string",
    "description": "이 호출을 하는 이유를 한두 문장으로 — 어떤 테이블·조인·컬럼을 왜 골랐는지.",
}


def tools_with_reason(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        if t["name"] == "finalize":
            out.append(t)
            continue
        schema = dict(t["input_schema"])
        schema["properties"] = {**schema.get("properties", {}), "reason": _REASON_PROP}
        schema["required"] = [*schema.get("required", []), "reason"]
        out.append({**t, "input_schema": schema})
    return out


#: 스키마 컨텍스트 섹션의 뜻(2026-10-14 사용자). 섹션 이름과 기호(`->`, `=`)만 있고 설명이 없어 모델이 짐작했다 —
#: `->` 는 FK 에선 "참조", 용어집에선 "이 표현은 이 컬럼"으로 두 뜻이었다. 컨텍스트에 실제로 있는 섹션만 설명한다.
_SCHEMA_LEGEND = (
    ("【Foreign keys】", "【Foreign keys】: 외래키 관계."),
    ("【Join paths】", "【Join paths】: 부모 테이블을 거치지 않고 바로 조인할 수 있는 관계. 외래키가 이 경로보다 우선하지 않는다."),
    ("[용어집]", "[용어집]: 질문 표현 -> 컬럼: 설명."),
)


def _schema_legend(schema_context: str) -> str:
    lines = [text for marker, text in _SCHEMA_LEGEND if marker in schema_context]
    return "\n".join(lines) + "\n\n" if lines else ""


@dataclass
class AnalysisResult:
    answer: str
    sql_steps: list[dict[str, Any]]
    from_cache: bool = False
    #: 실행(또는 검증)에서 실패한 SQL. sql_steps 는 성공한 SQL만 담으므로(캐시·화면이 그렇게
    #: 읽는다) 따로 둔다 — 평가 기록이 실패 원인을 보여 줄 수 있게(2026-10-06, seq 353).
    failed_sql: str | None = None
    #: ReAct 루프 안에서 발동한 가드 이름, 발동 순서대로(2026-10-06). 캐시 히트면 빈 목록.
    guards_fired: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        target_connector: PgConnector,
        settings: Settings,
        llm: BaseLLMClient,
        parser: SqlParser,
        target_name: str,
        *,
        system_pool: Any | None = None,
        schema_cache: SchemaCache | None = None,
        schema_vector: SchemaVectorIndex | None = None,
        glossary_store: GlossaryStore | None = None,
        rule_store: SqlRuleStore | None = None,
        stats_adapter: StatsAdapter | None = None,
        semantic_cache: SemanticCache | None = None,
        enrichment: QuestionEnricher | None = None,
        llm_overrides: dict[str, BaseLLMClient] | None = None,
    ) -> None:
        """llm_overrides: 파이프라인 단계별 전용 LLM. 키는 'react'|'generate_sql'|'summarize'
        ('enrich_detect'/'enrich_rewrite'는 QuestionEnricher 생성 시 별도로 주입한다). 지정 안
        된 단계는 기본 llm을 쓴다."""
        self._conn = target_connector
        self._settings = settings
        self._llm = llm
        self._parser = parser
        self._target_name = target_name
        self._system_pool = system_pool
        self._schema_cache = schema_cache
        self._schema_vector = schema_vector
        self._glossary_store = glossary_store
        self._rule_store = rule_store
        self._stats_adapter = stats_adapter
        self._semantic_cache = semantic_cache
        self._enrichment = enrichment
        self._llm_overrides = llm_overrides or {}
        self._initialized = False

    def _llm_for(self, stage: str) -> BaseLLMClient:
        return self._llm_overrides.get(stage, self._llm)

    @property
    def schema_vector(self) -> SchemaVectorIndex | None:
        return self._schema_vector

    async def list_schemas(self) -> list[str]:
        await self._ensure_initialized()
        return await self._conn.list_schemas()

    async def list_tables(self, schema: str) -> list[Any]:
        await self._ensure_initialized()
        return await self._conn.list_tables(schema)

    async def describe_table(self, schema: str, table: str) -> Any:
        await self._ensure_initialized()
        return await self._conn.describe_table(schema, table)

    async def list_indexes(self, schema: str) -> list[Any]:
        await self._ensure_initialized()
        return await self._conn.list_indexes(schema)

    async def explain(
        self, sql: str, *, analyze: bool = False, schema: str | None = None, timeout_seconds: float = 30,
    ) -> dict[str, Any]:
        """관리자용 실행계획 조회. 검증 계층을 거치지 않는다 — admin 전용 신뢰 경로."""
        await self._ensure_initialized()
        return await self._conn.explain(sql, analyze=analyze, schema=schema, timeout_seconds=timeout_seconds)

    async def analyze_sql_tuning(
        self, sql: str, *, schema: str = "public", on_step: OnStep | None = None, debug: bool = False,
    ) -> str:
        """SQL 튜닝 — 실행계획 분석, 재작성 제안, 인덱스 제안을 LLM 한 번 호출로 받는다.
        explain()과 마찬가지로 검증 계층을 거치지 않는 신뢰 경로다(신뢰 사용자만 접근하는
        분석 화면 전용, BIRD 문항 답변 경로와 무관). on_step/debug는 analyze()와 동일한
        패턴 — 질문분석 화면처럼 단계별 진행 상황을 보여달라는 요청으로 추가함."""
        t0 = time.monotonic()

        async def emit(msg: str) -> None:
            if on_step is not None:
                await on_step(msg)

        async def emit_debug(msg: str) -> None:
            if debug and on_step is not None:
                elapsed = time.monotonic() - t0
                await on_step(f"[디버그] (+{elapsed:.2f}s) {msg}")

        await self._ensure_initialized()
        await emit("실행계획 조회 중 (EXPLAIN ANALYZE)...")
        plan = await self.explain(sql, analyze=True, schema=schema, timeout_seconds=30)
        await emit_debug(
            f"실행계획 조회 완료: planning {plan['planning_time']}ms / execution {plan['execution_time']}ms\n"
            f"{json.dumps(plan['plan'], ensure_ascii=False, indent=2)}"
        )

        await emit("스키마 링킹 중...")
        # 자연어 질문 대신 SQL 원문으로 스키마 벡터 검색 — 테이블/컬럼명이 SQL에 그대로
        # 드러나므로 질문 기반 검색과 동일한 경로를 그대로 재사용할 수 있다.
        schema_context = await self._build_schema_context(sql, schema)
        await emit_debug(f"스키마 컨텍스트 {len(schema_context)}자 구성됨:\n{schema_context}")

        prompt = (
            "당신은 PostgreSQL 성능 튜닝 전문가입니다. 아래 SQL과 EXPLAIN (ANALYZE, BUFFERS) 결과를 "
            "보고 다음 세 가지를 한국어로 명확히 구분된 섹션으로 제시하세요:\n"
            "1. 병목 분석: Sequential Scan, 누락된 인덱스, 비효율적인 JOIN 순서 등 실행계획에서 "
            "확인되는 문제점을 구체적인 수치(비용, 실제 시간, 처리 행 수)와 함께 지적하세요.\n"
            "2. 쿼리 재작성 제안: 무거운 서브쿼리를 CTE로, 암시적 JOIN을 명시적 INNER/LEFT JOIN으로, "
            "WHERE 절이 인덱스를 활용하도록 개선한 SQL을 제시하세요 — 개선할 게 없으면 그대로 두고 "
            "이유를 설명하세요.\n"
            "3. 인덱스 제안: 스키마와 쿼리 패턴을 근거로 한 구체적인 인덱스(필요하면 복합 인덱스 포함) "
            "제안과 CREATE INDEX 문을 제시하세요.\n\n"
            f"[SQL]\n{sql}\n\n"
            f"[실행계획 (EXPLAIN ANALYZE, JSON)]\n{json.dumps(plan['plan'], ensure_ascii=False, indent=2)}\n"
            f"소요 시간: planning {plan['planning_time']}ms / execution {plan['execution_time']}ms"
        )
        if schema_context:
            prompt += f"\n\n[스키마 컨텍스트]\n{schema_context}"

        await emit("LLM 튜닝 분석 중...")
        tuning_llm = self._llm_for("sql_tuning")
        await emit_debug(f"시스템 프롬프트 ({len(prompt)}자), LLM provider: {tuning_llm.provider}\n{prompt}")
        resp = await tuning_llm.complete(system_prompt=prompt, messages=[{"role": "user", "content": sql}])
        usage_str = f", 토큰 사용량: {resp.usage}" if resp.usage else ""
        await emit_debug(f"LLM 응답 완료 ({len(resp.text or '')}자){usage_str}")
        return resp.text or ""

    async def analyze_design_lab_review(
        self, schema: str, *, on_step: OnStep | None = None, debug: bool = False,
        mode: str = "findings",
    ) -> dict[str, Any]:
        """Design Lab findings에 대한 LLM 의견 — 참고용, 확정된 제안이 아니다.

        Design Lab 본체(analyzer.py)는 일부러 결정론적이다 — 이 메서드는 그 결과를
        요약해 LLM에게 자유 의견을 구하는 것으로, 판단을 대신하지 않는다. 특히
        `repeating_group`/`mixed_grain`처럼 자동 DDL 제안이 없는(사람 판단이
        필요하다고 명시된) 항목에서 값어치가 있다(사용자 요청, 2026-09-15).

        새 LLM 스테이지를 따로 만들지 않고 `sql_tuning` 자리를 그대로 재사용한다 —
        사용자가 "신규 설정 없이"를 명시했고, 둘 다 "신뢰 사용자 전용 분석 화면에서
        기존 결과를 LLM에게 보여주고 의견을 구한다"는 같은 성격이다.

        mode="schema_only"는 findings 없이 **스키마 정의만** 준다(사용자 요청,
        2026-10-02). findings 모드는 LLM이 규칙이 찾은 항목밖에 못 봐서 의견이
        그 안에 갇힌다 — findings가 0건이면 아예 호출도 안 한다. 대신 데이터로
        검증하지 않으므로 이름·타입만 보고 한 추측이라는 점을 프롬프트에 박아둔다.

        반환: {"answer": 서술, "verdicts": ..., "additional": ..., "findings": ...}.
        findings 모드에서만 항목별 판정(F1..Fn → 동의/이견/보류)을 받는다
        (designlab/verdicts.py 참고) — 화면이 코드 항목과 LLM 의견의 일치를 구분한다.
        """
        from pgxnl.agent.designlab import analyze_schema

        t0 = time.monotonic()

        async def emit(msg: str) -> None:
            if on_step is not None:
                await on_step(msg)

        async def emit_debug(msg: str) -> None:
            if debug and on_step is not None:
                elapsed = time.monotonic() - t0
                await on_step(f"[디버그] (+{elapsed:.2f}s) {msg}")

        await self._ensure_initialized()
        if mode == "schema_only":
            return {"answer": await self._design_lab_review_schema_only(schema, emit, emit_debug)}
        await emit("Design Lab 재검토 중...")
        report = await analyze_schema(self, target_name=self._target_name, schema=schema)
        if not report.findings:
            return {"answer": "발견된 항목이 없어 의견을 낼 것이 없습니다."}

        # f.action(자동 DDL 제안이 없는 항목의 "지금 당장 할 수 있는 NL2SQL 대응")은
        # 일부러 뺐다 — pgxnl의 목적은 NL2SQL 정확도가 아니라 SQL 미숙련 사용자용
        # 자연어 Query 툴이고, Design Lab은 그 안에서 DBMS 이해를 돕는 도구다.
        # action까지 넣으면 LLM이 "NL2SQL 정확도 향상" 관점으로 답을 몰고 간다
        # (실측: 사용자 리포트, 2026-09-15) — 스키마 자체의 정규화 품질만 근거로 쓴다.
        from pgxnl.agent.designlab.verdicts import finding_id, parse_review

        findings_text = "\n".join(
            f"- {finding_id(i)} [{f.severity}/{f.normal_form}] {f.title}\n  근거: {f.detail}"
            for i, f in enumerate(report.findings)
        )
        await emit_debug(f"findings {len(report.findings)}건 정리됨:\n{findings_text}")

        prompt = (
            "당신은 데이터베이스 정규화 전문가입니다. 아래는 결정론적 규칙 기반 도구(Design Lab)가 "
            f"스키마 '{schema}'에서 찾아낸 정규화 관련 항목들입니다. 이 중 '이행 종속'과 '중복 개념'은 "
            "이미 기계적으로 DDL 제안이 나가지만, '반복 그룹'과 '혼합 단위'는 사람 판단이 필요해 "
            "자동 제안을 만들지 않습니다.\n\n"
            "자유롭게 의견을 제시하세요. 특히:\n"
            "1. 반복 그룹/혼합 단위 항목이 실제로 정규화가 필요한지, 필요하다면 어떤 방향이 좋을지\n"
            "2. 규칙 기반 탐지가 놓쳤을 수 있는 다른 정규화 이슈가 있는지\n"
            "3. 이미 자동 제안이 있는 항목이라도 다른 관점이 있다면\n\n"
            "판단 기준은 스키마 자체의 정규화 품질(데이터 무결성, 갱신 이상, 중복)입니다 — "
            "이 도구는 자연어 질의 정확도(NL2SQL) 향상을 위한 것이 아니니 그 관점으로 근거를 "
            "들지 마세요.\n\n"
            "당신의 의견은 참고용이며 확정된 제안이 아닙니다 — 실제 적용 여부는 사람이 결정한다는 "
            "점을 답변에서도 분명히 하세요.\n\n"
            # 응답 길이 상한(2026-10-02 실측): 판정 블록을 붙이자 응답이 길어져 호출 상한
            # 180초(자체 서빙 27B ≈ 19 tok/s → 약 3,400토큰)를 넘겼고, 재시도까지 겹쳐
            # 9분 뒤 실패했다. 본문은 판정 표가 이미 보여주는 것을 반복하지 않게 좁힌다.
            "본문은 간결하게(1,500자 이내) — 동의하는 항목은 본문에서 다시 설명하지 말고, 이견·보류 "
            "항목과 규칙이 놓친 것, 반복 그룹/혼합 단위의 방향만 다루세요.\n\n"
            "답변 맨 끝에, 각 항목(F1, F2, ...)에 대한 판정을 아래 형식의 ```json 블록 하나로 "
            "덧붙이세요. verdict는 agree(이 지적이 맞다)/disagree(정규화 문제가 아니다)/"
            "unsure(데이터를 더 봐야 안다) 중 하나, reason은 40자 이내 한 구절입니다. 규칙이 놓쳤다고 "
            "보는 것은 additional에 넣으세요(없으면 빈 배열). 이 블록은 화면이 따로 읽어 표로 "
            "보여줍니다.\n"
            '```json\n{"verdicts": [{"id": "F1", "verdict": "agree", "reason": "..."}], '
            '"additional": [{"title": "...", "tables": ["..."], "columns": ["..."], "reason": "..."}]}\n```\n\n'
            f"[발견된 항목 {len(report.findings)}건]\n{findings_text}"
        )

        await emit("LLM 의견 조회 중...")
        review_llm = self._llm_for("sql_tuning")
        await emit_debug(f"시스템 프롬프트 ({len(prompt)}자), LLM provider: {review_llm.provider}\n{prompt}")
        resp = await review_llm.complete(
            system_prompt=prompt,
            messages=[{"role": "user", "content": f"'{schema}' 스키마의 정규화에 대한 의견을 알려주세요."}],
        )
        usage_str = f", 토큰 사용량: {resp.usage}" if resp.usage else ""
        await emit_debug(f"LLM 응답 완료 ({len(resp.text or '')}자){usage_str}")
        parsed = parse_review(resp.text or "", len(report.findings))
        if parsed.verdicts is None:
            await emit_debug("판정 블록을 읽지 못함 — 서술만 표시")
        else:
            await emit_debug(f"판정 {len(parsed.verdicts)}/{len(report.findings)}건, 추가 지적 {len(parsed.additional)}건")
        return {
            "answer": parsed.text,
            # JSON 키는 문자열이어야 한다 — 화면은 findings[i].title 로 자기 목록과 짝짓는다
            # (검토 화면과 이 호출은 analyze_schema 를 따로 돌린다).
            "verdicts": None if parsed.verdicts is None else {str(i): v for i, v in parsed.verdicts.items()},
            "additional": parsed.additional,
            "findings": [{"id": finding_id(i), "title": f.title, "kind": f.kind}
                         for i, f in enumerate(report.findings)],
        }

    async def _design_lab_review_schema_only(self, schema: str, emit, emit_debug) -> str:
        """analyze_design_lab_review(mode="schema_only")의 본체 — 정의만 보고 의견."""
        from pgxnl.agent.designlab.schema_text import render_schema

        await emit("스키마 정의 읽는 중...")
        metas = [await self.describe_table(schema, t.name) for t in await self.list_tables(schema)]
        if not metas:
            return f"'{schema}' 스키마에 테이블이 없습니다."
        st = render_schema(metas)
        omitted_note = ""
        if st.omitted:
            omitted_note = (f"\n\n(분량 상한 때문에 테이블 {len(st.omitted)}개는 정의를 싣지 못했습니다: "
                            f"{', '.join(st.omitted)} — 이 테이블들에 대해서는 판단하지 마세요.)")
            await emit(f"분량 상한으로 테이블 {len(st.omitted)}개 제외: {', '.join(st.omitted)}")
        await emit_debug(f"스키마 정의 {st.included}개 테이블, {len(st.text)}자")

        prompt = (
            "당신은 데이터베이스 정규화 전문가입니다. 아래는 스키마 "
            f"'{schema}'의 테이블 정의(컬럼, 타입, PK, FK, 코멘트)입니다. 데이터는 제공되지 않습니다.\n\n"
            "이 정의만 보고 정규화 관점의 의견을 제시하세요:\n"
            "1. 1NF — 반복 그룹(번호 붙은 컬럼 묶음 등)이나 한 컬럼에 여러 값을 담는 구조\n"
            "2. 2NF/3NF — 키가 아닌 컬럼에 종속된 것으로 보이는 컬럼(이행 종속), "
            "여러 테이블에 사본으로 있는 같은 개념\n"
            "3. 누락된 것으로 보이는 PK/FK 제약, 한 테이블에 서로 다른 단위의 행이 섞인 구조\n"
            "4. 각 지적마다 어떻게 고치면 좋을지 방향\n\n"
            "중요: 실제 데이터로 확인하지 않았으므로 모든 지적은 이름과 타입에서 나온 **추측**입니다. "
            "확신 정도를 지적마다 밝히고, 데이터로 확인해야 할 것(예: 'A가 정말 B를 결정하는지 "
            "SELECT A, count(DISTINCT B) ... 로 확인')을 함께 적으세요.\n\n"
            "판단 기준은 스키마 자체의 정규화 품질(데이터 무결성, 갱신 이상, 중복)입니다 — "
            "자연어 질의 정확도(NL2SQL) 관점으로 근거를 들지 마세요.\n\n"
            "당신의 의견은 참고용이며 확정된 제안이 아닙니다 — 실제 적용 여부는 사람이 결정한다는 "
            "점을 답변에서도 분명히 하세요.\n\n"
            f"[테이블 정의 {st.included}개]\n{st.text}{omitted_note}"
        )

        await emit("LLM 의견 조회 중...")
        review_llm = self._llm_for("sql_tuning")
        await emit_debug(f"시스템 프롬프트 ({len(prompt)}자), LLM provider: {review_llm.provider}\n{prompt}")
        resp = await review_llm.complete(
            system_prompt=prompt,
            messages=[{"role": "user", "content": f"'{schema}' 스키마의 정규화에 대한 의견을 알려주세요."}],
        )
        usage_str = f", 토큰 사용량: {resp.usage}" if resp.usage else ""
        await emit_debug(f"LLM 응답 완료 ({len(resp.text or '')}자){usage_str}")
        return resp.text or ""

    async def execute_readonly(
        self, sql: str, *, row_limit: int | None = None, timeout_seconds: float | None = None,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """검증 계층을 거치지 않는 직접 실행 — BIRD 평가(gold/pred SQL 비교)처럼 신뢰된
        내부 호출자 전용. 사용자 질문 경로(analyze())는 절대 이 메서드를 쓰지 않는다.
        schema는 BIRD처럼 문항(db_id)마다 대상 스키마가 다를 때 지정한다."""
        await self._ensure_initialized()
        return await self._conn.execute_readonly(
            sql, row_limit=row_limit, timeout_seconds=timeout_seconds, schema=schema
        )

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        await self._conn.connect()
        self._initialized = True

    async def analyze(
        self, question: str, *, user_id: int, on_step: OnStep | None = None, schema: str = "public",
        debug: bool = False, evidence: str | None = None, use_cache: bool = True,
    ) -> AnalysisResult:
        """schema: 탐색/실행 기본 스키마. BIRD처럼 문항(db_id)마다 스키마가 다른
        평가 시나리오에서 orchestrator 하나(=하나의 DB 커넥션 풀)를 공유하면서도
        문항별로 올바른 스키마를 쓰기 위한 것 — 기본값 "public"은 일반 analyze 흐름과 동일하다.
        debug=True면 각 단계의 세부 정보(캐시 판정, 스키마 컨텍스트 크기, LLM 도구
        호출 결과, 검증 판정/비용 등)를 on_step으로 추가 전송한다.

        use_cache: False면 시맨틱 캐시 조회/저장을 모두 건너뛴다. BIRD 평가 배치처럼
        규칙/glossary를 바꿔가며 같은 30문항을 반복 실행해 전후 비교할 때, 캐시가
        켜져 있으면 바뀐 설정이 실제로는 하나도 적용 안 된 예전 캐시 응답이 그대로
        재사용돼 비교 결과가 오염된다(실측 확인: 30문항 배치를 반복 실행하는 동안
        `pgxnl_cache`에 hit_count>=1인 행이 실제로 쌓임). 평가 하네스(bird.py)는
        반드시 False로 호출할 것 — 대화형 analyze() 기본 흐름(캐시로 응답 속도를
        높이는 게 목적)은 True 기본값 그대로 둔다.

        evidence: BIRD 평가처럼 질문과 별도로 주어지는 참고 정보(예: "Exclusively virtual
        refers to Virtual = 'F'"). question 문자열에 미리 이어붙이지 말고 반드시 이
        인자로 전달할 것 — 질문 보강(enrichment)의 재작성 프롬프트는 "질문 한 문장으로
        압축"하는 게 목적이라, evidence가 question에 섞여 있으면 재작성 과정에서 evidence가
        조용히 사라지는 문제를 실측으로 확인했다(예: "Virtual = 'F'"라는 근거가 재작성된
        질문에서 빠져 모델이 다른 값을 추측함). enrichment는 question에만 적용하고, evidence는
        그 뒤에 원문 그대로 다시 붙여 스키마 링킹/SQL 생성/캐시 키에 전달한다."""
        t0 = time.monotonic()
        # 스키마 컨텍스트/프롬프트 전문은 길 수 있어 상한을 둔다 — 실제 LLM 호출에 쓰이는
        # system_prompt 자체는 잘리지 않는다(이 한도는 emit_debug 표시 전용). 규칙/few-shot이
        # 늘어나며 4000자로는 뒤쪽 규칙이 디버그 로그에서 안 보이는 걸 실측으로 확인해 올림.
        _DEBUG_TEXT_LIMIT = 20000

        async def emit(msg: str) -> None:
            if on_step is not None:
                await on_step(msg)

        async def emit_debug(msg: str) -> None:
            if debug and on_step is not None:
                elapsed = time.monotonic() - t0
                await on_step(f"[디버그] (+{elapsed:.2f}s) {msg}")

        def truncate(text: str) -> str:
            if len(text) <= _DEBUG_TEXT_LIMIT:
                return text
            return f"{text[:_DEBUG_TEXT_LIMIT]}... (총 {len(text)}자, 이하 생략)"

        await self._ensure_initialized()
        await emit_debug(f"대상: {self._target_name} / 스키마: {schema} / 원본 질문: {question}")

        # [2] 질문 보강 (§5.2, 기본 비활성) — evidence는 여기 관여하지 않는다(위 docstring 참고)
        await emit("질문 보강 중...")
        enriched = question
        if self._enrichment is not None:
            domain_hint = None
            if self._glossary_store is not None:
                # enrichment는 스키마 링킹 이전이라 어느 테이블이 관련 있는지 모른다 —
                # for_enrichment()가 테이블 무관하게 scope='enrich'/'both'인 항목만
                # 가져오므로(관리자가 미리 좁혀둔 집합), 여기서 질문/evidence와 키워드가
                # 겹치는 것만 다시 골라 토큰 낭비를 막는다(§5.11 scope 분리 참고).
                check = f"{question} {evidence}" if evidence else question
                entries = await self._glossary_store.for_enrichment(self._target_name, schema)
                relevant = _limit_glossary(
                    entries, check, self._settings.glossary_filter_threshold_chars
                )
                if relevant:
                    domain_hint = "\n".join(f"{e.term}: {e.definition}" for e in relevant)
                    await emit_debug(f"enrichment 도메인 지식 {len(relevant)}건 적용됨: {[e.term for e in relevant]}")
            result = await self._enrichment.enrich(question, evidence=evidence, domain_hint=domain_hint)
            enriched = result.text
            if result.debug_log:
                for entry in result.debug_log:
                    await emit_debug(
                        f"[{entry['call']}] 프롬프트:\n{truncate(entry['prompt'])}\n"
                        f"[{entry['call']}] 응답: {entry['response']}"
                    )
            if enriched != question:
                await emit_debug(f"질문 보강 결과: {enriched} (모호성 사유: {result.reasons})")
            if result.token_usage:
                await emit_debug(f"질문 보강 토큰 사용량: {result.token_usage}")

        # 보강이 끝난 뒤에야 evidence를 다시 붙인다 — 이후 단계(캐시/스키마 링킹/SQL 생성/
        # 요약)는 전부 이 full_question을 쓴다. "질문\n\n[참고 정보]\n증거"처럼 구조적으로
        # 분리하면 SQL 생성 단계 결과가 달라지는 걸 실측으로 확인했다(같은 BIRD 문항에서
        # RANK() 컬럼 위치가 바뀌어 EX 실패로 이어짐) — check_text와 동일한 이유로, 자연스럽게
        # 한 문장처럼 이어붙인 텍스트를 모델이 더 안정적으로 gold와 같은 구조로 처리한다.
        full_question = f"{enriched} {evidence}" if evidence else enriched
        # 스키마 링킹/캐시/SQL 생성/LLM에 실제로 넘어가는 최종 텍스트를 그대로 찍는다 —
        # evidence 조각만 따로 찍으면(예: "참고 정보 결합됨: ...") 정작 모델에 들어가는
        # 합쳐진 문장이 어떤 모양인지 디버그에서 확인할 수 없었다(실측 확인).
        await emit_debug(f"최종 질문(모델에 전달됨): {full_question}")

        guards_fired: list[str] = []  # ReAct 루프 안 가드 발동 기록(평가·디버그용)

        # [3] 시맨틱 캐시 조회 (§5.12) — Hit이어도 검증 계층은 아래에서 반드시 재통과
        await emit("캐시 조회 중...")
        cached = None
        if not use_cache:
            await emit_debug("캐시 사용 안 함(use_cache=False)")
        elif self._semantic_cache is not None:
            cached = await self._semantic_cache.lookup(full_question, self._target_name, schema)
        else:
            await emit_debug("시맨틱 캐시 비활성 상태")

        if cached is not None:
            await emit("캐시 히트")
            sql = cached.sql_steps[-1]["sql"] if cached.sql_steps else None
            await emit_debug(
                f"캐시 히트 — 저장된 질문: \"{cached.question}\" (hit_count={cached.hit_count}), 캐시된 SQL: {sql}"
            )
            if sql is None:
                return AnalysisResult(answer=cached.answer, sql_steps=cached.sql_steps, from_cache=True)
        else:
            await emit_debug("캐시 미스")
            # [4] 스키마 링킹 (§5.4)
            await emit("스키마 링킹 중...")
            schema_context = await self._build_schema_context(
                full_question, schema, select=True, emit_debug=emit_debug,
            )
            await emit_debug(f"스키마 컨텍스트 {len(schema_context)}자 구성됨:\n{truncate(schema_context)}")

            # [6] 거버넌스 레이어 로드 (§5.11) — schema_context에 섞지 않고 별도로 들고
            # 있다가 시스템 프롬프트 앞쪽에 직접 명령문으로 박아 넣는다. "아래 스키마
            # 컨텍스트 안에 규칙 섹션이 있으면 지키라"는 간접 참조 방식은, 규칙이 긴 스키마
            # 컨텍스트 뒤쪽에 묻혀 모델이 실제로는 안 지키는 사례를 실측으로 확인했다
            # (예: "RANK를 마지막 컬럼으로" 규칙이 있는데도 첫 컬럼에 배치).
            rules_text = ""
            few_shot_text = ""
            if self._rule_store is not None:
                rules = await self._rule_store.list_active(self._target_name, "generation_constraint", schema=schema)
                if rules:
                    rule_texts = [_format_generation_constraint(r.definition) for r in rules]
                    rules_text = "\n".join(f"{i}. {t}" for i, t in enumerate(rule_texts, 1))
                    await emit_debug(f"생성 규칙 {len(rules)}건 적용됨: {rule_texts}")

                # few_shot: "항상 X 해라/하지 마라" 절대 규칙 문장이 잘 안 먹히는 경계
                # 판단(예: 언제 컬럼을 추가해도 되는지)에 쓴다 — 구체적 질문+SQL 예시가
                # 추상적 규칙 문장보다 이런 판단을 더 잘 가르치는 걸 실측으로 확인했다.
                few_shots = await self._rule_store.list_active(self._target_name, "few_shot", schema=schema)
                if few_shots:
                    blocks = [_format_few_shot(r.definition) for r in few_shots]
                    few_shot_text = "\n\n".join(blocks)
                    await emit_debug(f"few-shot 예시 {len(few_shots)}건 적용됨")

            # [7] ReAct 루프 (§5.5)
            await emit("스키마 탐색 및 SQL 생성 중...")
            handlers, last_sql = self._build_tool_handlers(
                full_question, schema_context, schema, emit_debug, fired_log=guards_fired,
                quote_source=enriched,
            )
            react_llm = self._llm_for("react")
            planner = ReactPlanner(
                react_llm, tools_with_reason(TOOL_SCHEMAS) if debug else TOOL_SCHEMAS, handlers,
                max_iterations=self._settings.agent_max_iterations,
                max_seconds=(
                    self._settings.agent_max_seconds if self._settings.agent_max_seconds > 0 else None
                ),
            )
            system_prompt = self._build_system_prompt(
                schema_context, schema, rules_text, few_shot_text, evidence=evidence,
            )
            await emit_debug(f"시스템 프롬프트 ({len(system_prompt)}자):\n{truncate(system_prompt)}")
            # ReAct 의 첫 사용자 메시지. 시스템 프롬프트만 찍으면 질문(보강 표시 포함)이 이 구간에서
            # 안 보여, 모델이 받은 두 입력을 한곳에서 확인할 수 없었다(2026-10-13 사용자 지적).
            await emit_debug(f"사용자 메시지(질문, ReAct 첫 입력):\n{truncate(full_question)}")
            await emit_debug(f"최대 반복 횟수: {self._settings.agent_max_iterations}, LLM provider(react): {react_llm.provider}")
            try:
                answer = await planner.run(system_prompt, full_question, on_step=on_step, debug=debug)
            except TimeoutError:
                # 최대 반복 횟수를 넘겨도 generate_sql이 이미 유효한 SQL을 확보해뒀다면
                # (약한 모델이 finalize를 호출 안 하고 반복만 하는 경우) 그 SQL로 계속
                # 진행한다 — 이미 검증까지 통과한 결과를 통째로 버릴 이유가 없다.
                if last_sql[0] is None and last_sql[1] is None:
                    raise
                answer = ""

            sql = last_sql[0]  # generate_sql 핸들러가 채워둔 값 (아래 참고, 호출별 로컬 상태)
            if sql is None and last_sql[1] is not None:
                sql = last_sql[1]
                await emit_debug(f"[가드] 조언 후 모델이 SQL을 다시 내지 않고 끝냄 — 조언 전 SQL을 씁니다: {sql}")
            # 개별 발동은 위에서 그때그때 찍히지만 긴 디버그 로그에 묻힌다 — 루프가 끝나면
            # 한 줄로 모아 보여준다(발동 없음도 적는다: "안 걸렸다"도 확인할 정보다).
            await emit_debug(
                "[가드] 이 질의에서 발동: " + (", ".join(guards_fired) if guards_fired else "없음")
            )

        if sql is None:
            return AnalysisResult(
                answer=answer if cached is None else cached.answer, sql_steps=[], guards_fired=guards_fired,
            )

        # [7-b] canonical_rewrite — 예시 쌍으로 형태를 고치는 LLM 단계 (§5.8 앞).
        # 코드 Canonicalization보다 **먼저** 돈다: LLM이 형태를 제안하고, 그 결과를
        # 코드 규칙이 마지막으로 정규화한다(NULL 정렬·별칭·컬럼 순서). 순서를 뒤집으면
        # 코드가 맞춰 놓은 형태를 LLM이 도로 흐트러뜨릴 수 있다.
        if self._rule_store is not None:
            rw_defs = await self._rule_store.list_active(self._target_name, "canonical_rewrite", schema=schema)
            examples = load_rewrite_examples([r.definition for r in rw_defs])
            if examples:
                rewritten, reason = await rewrite_sql(
                    sql, examples, self._llm_for("canonical_rewrite"), self._parser,
                )
                if rewritten != sql:
                    await emit_debug(f"[재작성] 적용 — {reason}\n전: {sql}\n후: {rewritten}")
                    sql = rewritten
                else:
                    await emit_debug(f"[재작성] 미적용 — {reason}")

        # [8] SQL Canonicalization (§5.8)
        await emit("SQL 정규화 중...")
        canon_sql = sql
        if self._settings.canonicalization_enabled and self._rule_store is not None:
            rule_defs = await self._rule_store.list_active(self._target_name, "canonicalization", schema=schema)
            canon_rules = load_rules_from_store(
                rule_defs, await self._column_owners(schema, rule_defs),
                question=enriched, evidence=evidence,
                canonical_copies=await self._canonical_copies(schema, rule_defs),
                pk_columns=await self._pk_columns(schema, rule_defs),
                timestamp_columns=await self._timestamp_columns(schema, rule_defs),
            )
            canon_sql, applied = canonicalize_sql_verbose(sql, self._parser, canon_rules)
            if canon_sql != sql:
                # 어느 규칙이 실제로 일했는지 남긴다 — 규칙을 뺄지 판단하려면
                # "등록돼 있었다"가 아니라 "편집을 냈다"를 세야 한다.
                await emit_debug(f"[정규화] 적용 규칙: {', '.join(applied)}")
                await emit_debug(f"정규화 전: {sql}")
                await emit_debug(f"정규화 후: {canon_sql}")
            else:
                await emit_debug(
                    f"[정규화] 적용 규칙 없음 (활성 {len(canon_rules)}건: "
                    f"{', '.join(r.label() for r in canon_rules)})"
                )

        # [8-b] 컬럼 근거 설명 — **디버그일 때만** 돈다. 실패 분석에서 반복해서 부딪힌
        # 질문이 "이 컬럼이 결과로 요구된 것인가, 조건으로만 언급된 것인가"인데, 컬럼명
        # 리터럴 매칭으로는 안 풀린다("communication number" -> phone). 그건 모델이
        # 안다 — 그래서 모델에게 **질문 원문 인용**을 시키고, 인용이 실제 질문에 있는지는
        # 코드가 확인한다(지어낸 근거를 걸러내기 위함). 판정에는 쓰지 않는다.
        if debug:
            await self._emit_column_rationale(canon_sql, full_question, emit_debug)
            await self._emit_filter_rationale(canon_sql, schema, emit_debug)

        # [9] 검증 계층 (§5.9) — 캐시 히트 여부와 무관하게 항상 수행
        await emit("SQL 검증 중...")
        validation = await self._validate(canon_sql, user_id=user_id, question=full_question, schema=schema)
        await emit_debug(
            f"검증 판정: {validation.decision.value}"
            + (f", 사유: {validation.reason}" if validation.reason else "")
            + (f", 예상 비용: {validation.estimated_cost:.1f}" if validation.estimated_cost is not None else "")
        )
        if validation.decision != Decision.ALLOWED:
            return AnalysisResult(
                answer=f"요청을 처리할 수 없습니다: {validation.reason}", sql_steps=[], failed_sql=canon_sql,
                guards_fired=guards_fired,
            )

        # [10] 실행
        await emit("SQL 실행 중...")
        try:
            rows = await self._conn.execute_readonly(
                canon_sql, row_limit=self._settings.agent_sample_rows, timeout_seconds=30, schema=schema,
            )
        except Exception as exc:  # noqa: BLE001 — generate_sql은 문법만 검증하고 실행하지
            # 않으므로(위 [7] 참고), 별칭이 잘못된 컬럼 참조 같은 실행 시점 오류는 검증
            # 계층(§5.9)도 못 잡고 여기서 처음 드러난다. 안 잡으면 원본 DB 예외가 그대로
            # 위(API 라우트)까지 전파돼 검증 실패 때와 다르게 다듬어지지 않은 오류 문구가
            # 노출된다 — 같은 모양으로 맞춘다.
            await emit_debug(f"SQL 실행 오류: {exc}")
            return AnalysisResult(
                answer=f"요청을 처리할 수 없습니다: SQL 실행 오류 — {exc}", sql_steps=[], failed_sql=canon_sql,
                guards_fired=guards_fired,
            )
        await emit_debug(f"실행 결과 {len(rows)}행 반환됨, 샘플: {rows[:3]}")
        # ReAct 루프의 finalize() 답변은 실제 실행 결과를 보지 못한 채 작성된
        # 텍스트다(generate_sql은 문법 검증만 하고 실행하지 않는다) — 캐시 히트
        # 여부와 무관하게 항상 방금 실행한 rows를 근거로 답변을 새로 요약한다.
        final_answer, summarize_usage = await self._summarize(full_question, rows)
        if summarize_usage:
            await emit_debug(f"요약 토큰 사용량: {summarize_usage}")
        await emit_debug(f"요약 완료. 총 소요시간 {time.monotonic() - t0:.2f}s")

        # [11] 캐시 저장 (Canonicalization을 거친 SQL을 템플릿으로 저장)
        sql_steps = [{"sql": canon_sql}]
        if use_cache and self._semantic_cache is not None and cached is None:
            await self._semantic_cache.store(full_question, self._target_name, final_answer, sql_steps, schema)

        return AnalysisResult(
            answer=final_answer, sql_steps=sql_steps, from_cache=cached is not None, guards_fired=guards_fired,
        )

    async def run_sql(self, sql: str, *, user_id: int, schema: str = "public") -> dict[str, Any]:
        """"Query" 화면의 SQL 직접 입력 모드. analyze()와 동일한 Canonicalization +
        검증 계층을 통과시켜 실행하지만, ReAct 루프와 LLM 요약은 건너뛴다 — 사용자가
        이미 SQL을 알고 있으므로 결과는 표(rows)로 바로 보여주면 된다."""
        await self._ensure_initialized()

        canon_sql = sql
        if self._settings.canonicalization_enabled and self._rule_store is not None:
            rule_defs = await self._rule_store.list_active(self._target_name, "canonicalization", schema=schema)
            canon_rules = load_rules_from_store(
                rule_defs, await self._column_owners(schema, rule_defs),
                pk_columns=await self._pk_columns(schema, rule_defs),
                timestamp_columns=await self._timestamp_columns(schema, rule_defs),
            )
            canon_sql, _ = canonicalize_sql_verbose(sql, self._parser, canon_rules)

        validation = await self._validate(canon_sql, user_id=user_id, question=f"[SQL 직접 실행] {sql}", schema=schema)
        if validation.decision != Decision.ALLOWED:
            return {"sql": canon_sql, "rejected": True, "reason": validation.reason, "rows": []}

        rows = await self._conn.execute_readonly(
            canon_sql, row_limit=self._settings.agent_sample_rows, timeout_seconds=30, schema=schema,
        )
        return {"sql": canon_sql, "rejected": False, "reason": None, "rows": rows}

    async def describe_sql_question(self, sql: str, *, timeout_seconds: float = 30.0) -> str:
        """SQL 하나를 "이 SQL이 답하는 질문"으로 되돌린다 (`SQL 수집` 화면).

        수집된 실행 SQL은 실제로 쓰이는 질의다 — 사람이 쓰고 튜닝하고 운영에서 도는
        SQL이라, 같은 뜻의 질문이 들어왔을 때 파이프라인이 새로 만들어내는 SQL보다
        믿을 만하다. 여기에 질문을 붙여 시맨틱 캐시에 넣어두면 그 질문이 이 SQL로
        연결된다.

        **자동 등록은 하지 않는다.** 모델이 만든 문장을 사람이 보고 고쳐서 저장한다 —
        질문 문안이 곧 캐시 키(`pg_trgm` 유사도)라, 어긋난 문장을 넣으면 엉뚱한 질문이
        이 SQL에 걸린다.

        상한을 스스로 건다. 이 호출은 화면이 기다리는 조언성 호출이고, 사고(thinking)가
        켜진 모델은 이 정도 작업에도 수십 초를 쓴다(실측).
        """
        import asyncio

        await self._ensure_initialized()
        resp = await asyncio.wait_for(
            self._llm_for("describe_sql").complete(
                system_prompt=(
                    "당신은 데이터베이스 전문가입니다. 주어진 SQL이 답하는 질문을 "
                    "자연어 한 문장으로 쓰세요.\n"
                    "$1, $2 같은 표기는 pg_stat_statements가 값을 지운 자리표시자입니다 "
                    "— 사용자가 그때그때 넣는 값으로 보고, 그 자리를 자연스러운 말로 "
                    "바꿔 쓰세요(예: $1 -> \"특정 고객\").\n"
                    "설명도 SQL도 붙이지 말고 질문 문장만 출력하세요."
                ),
                messages=[{"role": "user", "content": f"SQL:\n{sql}"}],
            ),
            timeout=timeout_seconds,
        )
        return (resp.text or "").strip()

    async def cache_verified_sql(
        self, question: str, sql: str, *, schema: str = "public",
    ) -> dict[str, Any]:
        """질문과 **수집된 SQL**을 짝지어 시맨틱 캐시에 넣는다.

        캐시에 들어가는 것은 넘겨받은 SQL 그 자체다 — 이 질문으로 파이프라인을 한 번
        돌려서 나온 SQL이 아니다. 돌려서 넣으면 이 기능의 목적이 사라진다: 운영에서
        검증된 SQL을 캐시에 심으려는 것인데 LLM이 새로 만든 SQL로 바꿔치기하는 셈이다.

        넣기 전에 두 가지를 한다.

        1. **Canonicalization** — `SemanticCache.store()`가 요구한다. 정규화를 거치지
           않은 형태로 넣으면 캐시 히트 때 나가는 SQL과 미스 때 만들어지는 SQL의 모양이
           달라진다.
        2. **실제 실행** — 지금 이 스키마에서 도는지 확인한다. 수집 시점과 스키마가
           달라졌으면 여기서 걸린다. 실행 결과는 `answer` 요약에도 쓴다.

        `answer`는 캐시 히트 때 쓰이지 않는다(`analyze()`가 방금 실행한 rows로 답변을
        매번 새로 요약한다 — 데이터가 계속 바뀌기 때문이다). 그래도 채워 넣는 이유는
        컬럼이 NOT NULL이고, 관리 화면에서 이 항목이 무엇인지 사람이 알아볼 수 있어야
        하기 때문이다.

        검증 계층(§5.9)은 여기서 돌지 않는다 — 이 경로는 관리자 전용이고, 실제 사용자
        경로의 검증은 **캐시 히트 시점에** 다시 돈다(`analyze()`의 [9]는 캐시 히트
        여부와 무관하게 항상 수행된다). 그래서 여기에 넣는 것만으로 권한·PII 경계가
        뚫리지는 않는다.
        """
        await self._ensure_initialized()

        cache = self._semantic_cache
        if cache is None:
            raise RuntimeError("시맨틱 캐시가 비활성 상태입니다 (PGXNL_CACHE_ENABLED)")
        question = question.strip()
        if not question:
            raise ValueError("질문이 비어 있습니다")

        if await cache.exists(question, self._target_name, schema):
            return {"stored": False, "reason": "같은 질문이 이미 캐시에 있습니다", "sql": None}

        canon_sql = sql
        if self._settings.canonicalization_enabled and self._rule_store is not None:
            rule_defs = await self._rule_store.list_active(self._target_name, "canonicalization", schema=schema)
            canon_rules = load_rules_from_store(
                rule_defs, await self._column_owners(schema, rule_defs),
                pk_columns=await self._pk_columns(schema, rule_defs),
                timestamp_columns=await self._timestamp_columns(schema, rule_defs),
            )
            canon_sql, _ = canonicalize_sql_verbose(sql, self._parser, canon_rules)

        rows = await self._conn.execute_readonly(
            canon_sql, row_limit=self._settings.agent_sample_rows, timeout_seconds=30, schema=schema,
        )
        answer, _ = await self._summarize(question, rows)
        await cache.store(question, self._target_name, answer, [{"sql": canon_sql}], schema)
        return {"stored": True, "sql": canon_sql, "row_count": len(rows), "answer": answer}

    async def _build_schema_context(
        self, question: str, schema: str | None = None, *, select: bool = False, emit_debug: Any = None,
    ) -> str:
        """select=True 면 임베딩 후보에서 LLM 테이블 선택 단계를 한 번 더 거친다(table_select_enabled 일 때).
        그때 임베딩은 재현율 위주로 넓게 뽑고(table_select_candidate_margin), 줄이는 일은 선택 단계가 한다."""
        if self._schema_vector is None or not self._schema_vector.enabled:
            return ""  # 필수/보조 원칙: 임베딩 비활성 시 빈 컨텍스트로 폴백, ReAct가 search_tables로 탐색
        selecting = select and self._settings.table_select_enabled
        try:
            candidates = await self._schema_vector.search(
                question, self._settings.schema_vector_top_k,
                score_margin=(
                    self._settings.table_select_candidate_margin if selecting
                    else self._settings.schema_vector_score_margin
                ),
                schema=schema,
                keep_all_max=self._settings.schema_vector_keep_all_max_tables,
            )
        except Exception:  # noqa: BLE001
            # 위의 "비활성" 분기와 **같은 폴백**이다. 예전에는 비활성만 처리하고 실행 중
            # 실패는 예외를 그대로 올려서, 임베딩 서버가 잠깐 흔들리면 모든 요청이 죽었다 —
            # 2026-09-03 하루에만 watsonx 401과 임베딩 500으로 평가 run 7개(210문항)를
            # 통째로 잃었다. 스키마 링킹은 보조 컴포넌트이므로(설계 원칙 1) 실패해도
            # ReAct가 search_tables/describe_table로 스키마를 찾을 수 있어야 한다.
            logger.warning("스키마 벡터 검색 실패, 빈 컨텍스트로 폴백합니다", exc_info=True)
            return ""
        # glossary_store를 후보 테이블마다 붙인다 — 예전엔 describe_table 도구를 명시적으로
        # 호출해야만 노출됐는데, 지금 시스템 프롬프트는 schema_context에 이미 있는 테이블은
        # describe_table을 다시 부르지 말라고 유도해서 사실상 죽어있는 경로였다. DB catalog
        # comment(obj_description/col_description)만으로는 코드값 매핑(DOC/SOC 등)까지
        # 커버가 안 되는 걸 실측으로 확인해 여기서 직접 연결한다.
        #
        # **용어집을 독립 섹션으로 분리하려던 시도를 되돌렸다(2026-09-04, run 204~206).**
        # 각 테이블 블록 뒤에 붙는 지금 구조에는 실제 결함이 있다 — 용어집을 등록할수록
        # 그 테이블 블록만 커지고, 모델은 **가장 큰 블록의 테이블을 고른다**(seq 443을
        # 설정별 4회씩, 분산 0). 그런데 분리해 보니 EX가 19.67 -> 15.67로 떨어졌다.
        #
        # 이유: 용어집 11건이 schools에 몰려 있어 schools 블록이 가장 컸고, **gold도
        # 79%(11/14)가 schools에서 학교 이름을 가져온다.** 편향이 우연히 정답과 맞아떨어져
        # 있었다. 블록을 균등하게 만들자 편향이 사라지면서 이번엔 frpm으로 쏠렸다
        # (441, 462가 그렇게 깨졌다) — 어느 쪽이든 근거 없이 큰 쪽으로 가는 것은 같다.
        #
        # 근본 원인은 스키마가 정규화되지 않아 같은 개념(학교 이름)이 3개 테이블에 있고
        # 값까지 2.5~4.5% 갈리는 것이다. **"이 개념의 주인은 어느 테이블인가"를 알려주는
        # 결정론적 신호**(FK 방향 등)를 schema_context에 넣기 전까지는, 배치를 어떻게 바꿔도
        # 우연에 좌우된다. 그 신호가 생긴 뒤에 이 분리를 다시 시도한다.
        blocks = []
        for c in candidates:
            block = to_mschema_from_candidate(c)
            if self._glossary_store is not None:
                terms = await self._glossary_store.for_table(self._target_name, c.schema, c.table)
                terms = _limit_glossary(terms, question, self._settings.glossary_filter_threshold_chars)
                if terms:
                    # term(질문 쪽 표현) -> column_name(컬럼) -> definition(설명)이 용어집의
                    # 세 축인데, 예전엔 column_name이 있으면 term을 통째로 버렸다. 그러면
                    # "사용자가 이렇게 말하면 이 컬럼"이라는 매핑 자체가 모델에 도달하지
                    # 않아 항목이 무력화된다 — BIRD 447에서 'doc type of schools' -> doc을
                    # 등록했는데도 모델이 doctype을 골랐다. 오히려 역효과였다: 정의가 나열한
                    # 설명 문자열("County Office of Education (COE)" 등)이 doctype 컬럼의
                    # 실제 값과 같아서, 매핑 없이 정의만 보면 doctype을 가리킨다.
                    lines = [f"{_glossary_label(t)}: {t.definition}" for t in terms]
                    block += "\n[용어집]\n" + "\n".join(lines)
            blocks.append(block)
        if selecting and len(candidates) > self._settings.schema_vector_keep_all_max_tables:
            blocks = await self._select_table_blocks(question, candidates, blocks, emit_debug)
        return "\n\n".join(blocks)

    async def _select_table_blocks(self, question: str, candidates: list, blocks: list[str], emit_debug: Any) -> list[str]:
        """LLM 테이블 선택(2026-10-15). 테이블이 적은 스키마는 호출 전에 건너뛴다(keep_all_max_tables 이하 —
        california 실험에서 단일 테이블로 충분하다고 잘못 판단해 4문항 위험). 실패하거나 아무것도
        못 고르면 후보 전체를 그대로 쓴다(설계 원칙 1: 보조 단계가 필수 경로를 막지 않는다)."""
        from pgxnl.agent.table_select import select_tables

        names = [c.table for c in candidates]
        llm = self._llm_overrides.get("table_select") or self._llm_for("react")
        t0 = time.monotonic()
        try:
            sel = await select_tables(llm, question, "\n\n".join(blocks), set(names))
        except Exception:  # noqa: BLE001
            logger.warning("테이블 선택 실패 — 후보 전체를 씁니다", exc_info=True)
            if emit_debug:
                await emit_debug("[테이블 선택] 실패 — 임베딩 후보 전체 사용")
            return blocks
        if emit_debug:
            await emit_debug(
                f"[테이블 선택] ({time.monotonic() - t0:.1f}s) 후보 {names} → {sel.tables or '(없음)'}"
                f"{' / 조인 ' + str(sel.joins) if sel.joins else ''}\n이유: {sel.reason or sel.error or '-'}"
            )
        if not sel.tables:
            return blocks
        keep = {t.lower() for t in sel.tables}
        return [b for c, b in zip(candidates, blocks) if c.table.lower() in keep]

    def _build_system_prompt(
        self, schema_context: str, schema: str = "public", rules_text: str = "", few_shot_text: str = "",
        evidence: str | None = None,
    ) -> str:
        base = (
            "당신은 PostgreSQL 데이터 분석 에이전트입니다. 절차는 정확히 다음과 같습니다: "
            "(1) 필요하면 도구로 스키마를 확인하고, (2) generate_sql을 정확히 한 번 호출해 SQL을 만든 뒤, "
            "(3) 결과가 'sql' 필드로 성공 반환되면 더 확인하지 말고 바로 finalize를 호출하세요. "
            "generate_sql은 문법만 검증할 뿐 실행하지 않으므로 실제 데이터를 볼 수 없습니다 — "
            "finalize의 answer에는 실제 결과를 몰라도 되는 짧은 확인 문구만 적으면 됩니다 "
            "(실제 사용자 응답은 시스템이 SQL을 실행한 뒤 별도로 생성합니다). "
            "generate_sql을 이미 성공했다면 같은 SQL을 다시 생성하지 말고 즉시 finalize를 호출하세요."
        )
        if schema and schema != "public":
            base += f" 이 질문의 대상 스키마는 \"{schema}\"입니다 — 테이블명을 스키마 없이 그대로 쓰면 됩니다(search_path에 이미 반영됨)."

        # 규칙/few-shot은 "아래 스키마 컨텍스트에 규칙 섹션이 있으면 참고하라"는 간접
        # 참조 대신, 여기서 직접 명령문으로 박아 넣는다 — 스키마 컨텍스트(테이블 목록)가
        # 길면 뒤에 붙는 규칙이 참고 정보 취급을 받아 무시되는 사례를 실측으로 확인했다
        # (예: "RANK를 마지막 컬럼으로" 규칙이 있는데도 지켜지지 않음). 스키마보다 먼저,
        # 번호 매긴 명령 목록으로 제시하면 우선순위가 명확해진다.
        if rules_text:
            base += f"\n\n다음 SQL 생성 규칙을 예외 없이 지키세요 — 참고 정보가 아니라 필수 준수 사항입니다:\n{rules_text}"
        if few_shot_text:
            base += f"\n\n다음 예시가 보여주는 판단 기준을 이번 질문에도 동일하게 적용하세요:\n{few_shot_text}"

        # evidence는 질문 텍스트에도 이어붙지만(full_question), 거기서는 "참고 정보"로
        # 읽혀 모델이 자기 상식으로 덮어쓴다 — BIRD 445에서 evidence가 "Street, City,
        # State and zip code"라고 컬럼을 지목했는데도 "communication address는 보통 우편
        # 주소"라며 mailstreet/mailcity를 골랐다. 그래서 준수 사항으로 한 번 더 제시한다.
        #
        # 뒷문장(결과 구성은 질문이 정한다)이 필요한 이유 — 초판은 evidence 전체를 통째로
        # 격상시켰고, 445는 고쳤지만 세 문항이 각각 다른 축으로 깨졌다(run 239):
        #   441 이름이 비슷한 다른 테이블의 컬럼으로 이동 / 454 컬럼 개수 증가 / 466 순서 역전
        #
        # 측정(2026-09-08, 같은 설정 재현 확인됨 — 247·248이 문항 단위까지 동일):
        #   강조 O  EX 23 (run 245)   강조 X  EX 20 (run 246·247·248)
        # 어제는 강조가 음수로 보였으나 그건 룰 7·ambiguous_column 가드가 없던 조합에서였다.
        if evidence:
            base += (
                "\n\n다음 참고 정보가 특정 컬럼·값·계산식을 지목하면 그것을 쓰세요 — "
                "일반적인 통념을 근거로 다른 컬럼이나 다른 값을 고르지 마세요. 단, 결과에 "
                "어떤 컬럼을 어떤 순서로 넣을지는 오직 질문이 정합니다: 참고 정보에 "
                "언급됐다는 이유로 컬럼을 추가하거나 순서를 바꾸지 마세요.\n"
                f"{evidence}"
            )

        if not schema_context:
            return base
        return f"{base}\n\n[스키마 컨텍스트]\n{_schema_legend(schema_context)}{schema_context}"

    def _build_tool_handlers(
        self, question: str, schema_context: str, schema: str = "public",
        emit_debug: Any = None, fired_log: list[str] | None = None, quote_source: str | None = None,
    ) -> tuple[dict[str, Any], list[str | None]]:
        """두 번째 반환값(원소 1개짜리 리스트)이 generate_sql이 채운 마지막 SQL을 담는다.
        self에 저장하면 안 된다 — Orchestrator는 대상 DB 하나당 공유되는데(state.orchestrators),
        analyze()가 동시에 여러 건 실행될 수 있어(BIRD 평가 concurrency=3, 또는 여러 사용자가
        같은 대상에 동시 질의) self._last_generated_sql처럼 인스턴스 속성에 저장하면 동시
        요청끼리 서로의 SQL을 덮어써 엉뚱한 질문에 다른 질문의 답을 반환하는 레이스
        컨디션이 생긴다 — 실측으로 확인됨(BIRD 평가에서 서로 다른 두 문항이 완전히
        동일한 SQL/답을 반환)."""
        # [0] 모든 가드를 통과한 SQL, [1] 조언형 가드가 되돌려 보낸 마지막 SQL(실행 불가 판정은 통과한 것).
        # 조언은 "이상해 보인다"일 뿐이라 모델이 고치지 않고 바로 finalize 하면 [1]을 쓴다 — 전엔 그 SQL이
        # 어디에도 저장되지 않아 "SQL 없음"으로 끝났다(2026-10-07 california seq 467: ambiguous_column
        # 발동 후 finalize, 설명문만 반환).
        last_sql: list[str | None] = [None, None]
        # 이미 한 번 조언을 돌려준 검사들. stats_guard / single_column은 "실행하면 실패한다"가
        # 아니라 "이상해 보인다"는 **조언**이라, 같은 말을 반복해도 새 정보가 없다. 그런데도
        # 반복하면 모델이 A -> B -> A 로 오가며 루프를 소진한다 — 중복 가드는 **검증을 통과한**
        # SQL만 기억하므로(last_sql[0]) 되돌려진 SQL끼리의 왕복은 잡지 못한다. 실측(run 230,
        # seq 441): 조언이 매번 나가 20회 반복을 넘겨 SQL을 아예 못 냈다(TimeoutError).
        # 그래서 조언은 질의당 검사별 한 번만 하고, 그 뒤에는 모델의 판단을 존중해 통과시킨다.
        advised: set[str] = set()

        async def _fired(name: str, message: str) -> str:
            """가드 발동을 디버그에 **이름과 함께** 남긴다.

            반환값(모델에게 가는 관찰 결과)은 손대지 않는다 — 라벨을 붙이면 프롬프트가
            달라져 측정이 흔들린다. 디버그에서 어느 가드가 왜 걸렸는지 보이는 것이 목적이다.
            """
            # fired_log: 평가 기록용. 괄호 앞 짧은 이름만 남긴다("aggregate_mix").
            if fired_log is not None:
                fired_log.append(name.split("(", 1)[0])
            if emit_debug is not None:
                await emit_debug(f"[가드] {name} 발동 — {message}")
            return message

        async def _search_tables(args: dict) -> Any:
            return await search_tables(self._conn, self._schema_cache, self._target_name, schema, args["keyword"])

        async def _describe_table(args: dict) -> Any:
            return await describe_table(
                self._conn, self._schema_cache, self._glossary_store,
                self._target_name, args["schema"], args["table"],
            )

        async def _sample_data(args: dict) -> Any:
            return await sample_data(
                self._conn, args["schema"], args["table"],
                row_limit=self._settings.agent_sample_data_rows,
            )

        async def _collect_stats(args: dict) -> Any:
            return await collect_stats(
                self._conn, self._stats_adapter, self._schema_cache, self._target_name,
                args["schema"], args["table"], args["column"], top_n=self._settings.agent_stats_top_n,
            )

        async def _generate_sql(args: dict) -> Any:
            # ReAct 루프의 LLM은 이미 describe_table/sample_data 등으로 실제 스키마를
            # 대화 맥락에 갖고 있다 — 그 맥락으로 이미 작성한 SQL을 sql 인자로 넘겨주면
            # 그것을 그대로 쓴다(문법만 검증). 정적 schema_context로 매번 새로 눈먼
            # LLM 호출을 하는 것보다 훨씬 정확하다 — 그쪽은 describe_table로 알아낸
            # 내용을 전혀 모르기 때문에 존재하지 않는 테이블명을 추측하기 쉽다.
            provided_sql = (args.get("sql") or "").strip()
            if provided_sql:
                if provided_sql == last_sql[0]:
                    # 이미 검증 통과한 SQL을 그대로 다시 보냄 — 진전이 없으므로 finalize를
                    # 강하게 유도한다. 약한 모델이 generate_sql만 반복 호출하다 최대
                    # 반복 횟수를 넘기는 것을 막기 위한 안전장치(프롬프트 안내만으로는
                    # 신뢰할 수 없어 서버 쪽에서도 방지한다).
                    return "이미 검증된 SQL입니다. 다시 생성하지 말고 지금 바로 finalize를 호출하세요."
                try:
                    stmt = self._parser.parse(provided_sql)
                except Exception as exc:  # noqa: BLE001 — 문법 오류는 관찰 결과로 LLM에 돌려줌
                    return f"SQL 문법 오류: {exc}"
                # parse()는 문법 오류에 예외를 던지지 않는다(ANTLR이 복구해 불완전한 트리를
                # 돌려준다) — 위 except만으로는 아무것도 못 잡았다. 오류 목록을 직접 본다.
                if not stmt.is_well_formed:
                    return "SQL 문법 오류: " + "; ".join(stmt.syntax_errors[:3])

                # 실행하면 반드시 실패하는 SQL은 여기서 되돌린다. 검증 계층(§5.9)도 같은
                # 검사를 하지만 그쪽은 ReAct 루프가 **끝난 뒤**라 모델이 고칠 기회가 없다 —
                # 실측(seq 454)에서 8개 run 내내 같은 SQL로 실패했다.
                # 참조한 컬럼이 그 테이블에 없으면 실행에서 반드시 죽는다. 검증 계층이
                # 이미 정확히 진단하지만 그쪽은 루프가 끝난 뒤라 모델이 못 본다 —
                # 실측(BIRD 459): `T1.street` (T1=satscores)로 8개 run 내내 거부됐다.
                # AliasFixRule도 못 고친다(조인을 새로 추가해야 하므로) — 모델에게 넘긴다.
                #
                # **`advised` 게이팅을 쓰지 않는다.** 아래 alias_scope·scalar_subquery·
                # window_misuse와 같은 부류이므로 고칠 때까지 매번 되돌린다.
                # [[advisory_once_policy]]는 "이상해 보인다"는 **조언**에 대한 것이다 —
                # 같은 말을 반복해도 새 정보가 없어 모델이 A->B->A로 오가며 루프를
                # 소진한다. 그러나 "실행하면 죽는다"는 반복해도 새 정보다: 안 고치면
                # SQL이 나가지 못해야 한다. 한 번만 알리던 동안 실측으로 모델이 조언을
                # 무시하고 그대로 실행돼 죽었다 — run 310·312의 seq 447이 두 번 연속
                # `column t3."Enrollment (K-12)" does not exist` 로 실패했다.
                if "missing_column" not in advised:
                    missing = await self._check_missing_columns(stmt, schema)
                    if missing:
                        advised.add("missing_column")
                        return await _fired("missing_column(그 테이블에 없는 컬럼)", missing[0].message())

                # 바깥 쿼리가 서브쿼리 안의 별칭을 참조하면 실행에서 반드시 죽는다.
                # 문법은 맞아 generate_sql을 통과하고 검증 계층도 별칭 스코프를 안 보므로,
                # 여기서 막지 않으면 ReAct 루프가 끝난 뒤 실패해 모델이 고칠 기회가 없다
                # (실측: 최근 22개 run에서 `missing FROM-clause entry` 13건, seq 454가 매번).
                unresolved = find_unresolved_aliases(stmt)
                if unresolved:
                    return await _fired("alias_scope(서브쿼리 별칭을 바깥에서 참조)", unresolved[0].message())

                # SELECT 목록의 서브쿼리가 2컬럼 이상이면 실행에서 반드시 죽는다
                # (subquery must return only one column). 문법은 맞아 여기를 통과하고
                # 컬럼 근거 검사도 못 잡는다 — 그쪽은 세 컬럼 모두 질문 구절에
                # 대응하므로 [REQUESTED] ✓ 를 준다. 실측: BIRD 465.
                multi = find_multicolumn_scalar_subqueries(stmt)
                if multi:
                    return await _fired("scalar_subquery(스칼라 서브쿼리 컬럼 개수)", multi[0].message())

                # GROUP BY 없이 집계와 비집계 컬럼을 섞으면 실행에서 반드시 죽는다
                # (must appear in the GROUP BY clause). 실측: card_games seq 353 이 CASE 를
                # SUM 으로 감싸지 않아 run 358·360 에서 실패. 같은 부류라 advised 게이팅 없음.
                mixed = find_aggregate_mix(stmt)
                if mixed:
                    return await _fired("aggregate_mix(GROUP BY 없는 집계·비집계 혼용)", mixed[0].message())

                misused = window_misuse_clause(stmt)
                if misused:
                    return await _fired("window_misuse(WHERE/HAVING의 OVER)", (
                        f"SQL을 다시 작성하세요. {misused} 절에는 윈도우 함수(OVER)를 쓸 수 없습니다. "
                        "윈도우 함수를 서브쿼리의 SELECT에서 별칭으로 계산한 뒤, 바깥 쿼리의 "
                        "WHERE에서 그 별칭으로 거르세요. 예) SELECT c FROM (SELECT c, "
                        "RANK() OVER (...) AS rnk FROM t WHERE ...) AS x WHERE x.rnk <= 5"
                    ))

                # 질문에 있던 필터 값을 변형했으면 되돌려 스스로 고치게 한다. 코드가
                # 직접 치환하지 않는 이유: 모델이 의도적으로 다른 값을 쓴 경우까지
                # 덮어쓰면 조용한 오답이 된다("모호하면 손대지 않는다", ADR-0009).
                # 같은 SQL을 다시 보내면 위 중복 가드에 걸려 무한 반복은 되지 않는다.
                # 리터럴 가드도 조언이다 — "질문의 값과 다르다"는 신호일 뿐, 그 SQL이
                # 실행에 실패한다는 뜻이 아니다. 한 번만 알리고 그 뒤에는 모델 판단을
                # 존중한다. 실측(BIRD 445): gold의 값 'High Schools (Public)'을 모델이
                # 맞게 냈는데 질문에 그 문자열이 없다는 이유로 17회 연속 거부돼
                # 타임아웃했다 — 질문에 없는 값을 쓰라고 요구하는 것이라 모델이 따를
                # 방법 자체가 없었다.
                if "literal" not in advised:
                    mutations = self._check_question_literals(stmt, question, quote_source)
                    mutations = await self._drop_real_values(mutations, stmt, schema)
                    if mutations:
                        advised.add("literal")
                        last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                        return await _fired(
                            "literal(질문의 값을 변형)",
                            "SQL을 다시 작성하세요. " + " ".join(m.message() for m in mutations),
                        )

                # 데이터 분포와 어긋나는지 본다(agent/stats_guard.py). 위 두 검사와 달리
                # 실행하면 "실패"하는 SQL이 아니라 **조용히 이상한 결과**를 내는 SQL을
                # 잡는 것이라, 되돌리되 다시 쓰라고 강제하지 않는다 — 모델이 그대로 두기로
                # 판단하면 같은 SQL을 다시 보낼 것이고 위의 중복 가드가 finalize로 보낸다.
                if "stats_guard" not in advised:
                    empty = await self._check_empty_columns(stmt, question, schema)
                    if empty:
                        advised.add("stats_guard")
                        last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                        return await _fired(
                            "stats_guard(대부분 비어 있는 컬럼)", " ".join(w.message() for w in empty),
                        )

                # 필터 값이 다른 컬럼에서도 흔한 값인가(컬럼 선택 모호). 판정하지 않고
                # 사실만 돌려준다 — 어느 쪽이 맞는지는 질문의 뜻에 달렸다.
                if "ambiguous_column" not in advised:
                    ambiguous = await self._check_ambiguous_columns(stmt, schema)
                    if ambiguous:
                        advised.add("ambiguous_column")
                        last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                        return await _fired(
                            "ambiguous_column(값이 여러 컬럼에 흔함)",
                            " ".join(w.message() for w in ambiguous),
                        )

                # 질문이 한 가지만 요구했는데 SELECT가 여러 개인가(§question_guard 3).
                # stats_guard와 달리 데이터를 안 보므로 비용이 0이다.
                if "single_column" not in advised:
                    unrequested = await self._check_unrequested_columns(stmt, question, schema)
                    if unrequested:
                        advised.add("single_column")
                        last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                        return await _fired("single_column(컬럼 개수)", unrequested.message())

                # 위 single_column은 개수만 본다("하나만 요구했는데 SELECT가 여럿"). 이쪽은
                # 항목마다 근거 구절을 받아 **어느 컬럼이** 군더더기인지 지목한다 — 모델이
                # 무엇을 지울지 알 수 있어야 조언이 실행 가능하다. LLM 호출이 하나 늘므로
                # 규칙으로 켜야 동작한다.
                # 조인해 놓고 조건에 안 쓰면서 그 테이블의 컬럼을 결과에만 넣는 경우.
                # 같은 값이 이미 조인된 테이블에 사본으로 있다면, 조인을 새로 만들면서까지
                # 갈아탈 이유가 있는지 되묻는다. LLM 호출 없이 파싱 + 캐시된 사본 맵만 쓴다.
                if "redundant_join" not in advised:
                    redundant = await self._check_redundant_joins(stmt, schema)
                    if redundant:
                        advised.add("redundant_join")
                        last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                        return await _fired(
                            "redundant_join(조건에 안 쓰는 조인)",
                            " ".join(r.message() for r in redundant),
                        )

                # 1쪽 키를 세면서 N쪽 자식과 조인해 개수가 부푸는 경우(팬아웃). 1쪽 개수인지
                # N쪽 개수인지는 질문에 달려 있어 사실만 알린다(agent/fanout_count.py).
                if "fanout_count" not in advised:
                    fanout = await self._check_fanout_counts(stmt, schema)
                    if fanout:
                        advised.add("fanout_count")
                        last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                        return await _fired(
                            "fanout_count(1:N 조인으로 부푼 COUNT)", " ".join(f.message() for f in fanout),
                        )

                if "grouped_rows" not in advised and await self._check_grouped_rows(stmt, question, schema):
                    from pgxnl.agent.grouped_rows import MESSAGE as _GROUPED_MSG
                    advised.add("grouped_rows")
                    last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                    return await _fired("grouped_rows(그룹별 행만 나옴)", _GROUPED_MSG)

                if "per_group_top" not in advised and await self._check_per_group_top(stmt, question, schema):
                    from pgxnl.agent.per_group_top import MESSAGE as _PER_GROUP_MSG
                    advised.add("per_group_top")
                    last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                    return await _fired("per_group_top(그룹별 1위를 LIMIT 1 로 자름)", _PER_GROUP_MSG)

                if "column_rationale" not in advised:
                    extra = await self._check_column_rationale(stmt, question, provided_sql, schema)
                    if extra:
                        advised.add("column_rationale")
                        last_sql[1] = provided_sql  # 조언형 — 모델이 고치지 않고 끝내면 이 SQL을 쓴다
                        return await _fired("column_rationale(질문에 근거 없는 컬럼)", extra.message())

                last_sql[0] = provided_sql
                return {"sql": provided_sql, "note": "검증 완료. 더 확인할 필요 없이 바로 finalize를 호출하세요."}

            sql = await generate_sql(
                self._llm_for("generate_sql"), self._parser, question, schema_context,
                max_corrections=self._settings.agent_max_corrections,
            )
            last_sql[0] = sql
            return {"sql": sql}

        handlers = {
            "search_tables": _search_tables,
            "describe_table": _describe_table,
            "sample_data": _sample_data,
            "collect_stats": _collect_stats,
            "generate_sql": _generate_sql,
        }
        return handlers, last_sql

    async def _check_empty_columns(self, stmt: Any, question: str, schema: str) -> list:
        """SELECT에 사실상 비어 있는 컬럼이 있는지 검사한다(stats_guard 규칙).

        규칙이 하나도 등록돼 있지 않으면 아무 일도 하지 않는다 — 발동 낱말을 코드에 박지
        않고 관리자가 정하게 한다. 어떤 이유로든 실패하면 조용히 넘어간다: 보조 검사가
        필수 경로(SQL 생성)를 막으면 안 된다(설계 원칙 1).
        """
        if self._rule_store is None or self._stats_adapter is None:
            return []
        try:
            rules = await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
            if not rules:
                return []
            ir = self._parser.to_ir(stmt)
            if ir is None:
                return []

            found: list = []
            for rule in rules:
                parsed = parse_stats_guard_rule(rule.definition)
                if parsed is None:
                    continue
                triggers, threshold = parsed
                found += await check_empty_columns(
                    ir, question=question, alias_to_table=stmt.alias_to_table,
                    lookup=self._stats_adapter.get_null_frac, triggers=triggers,
                    threshold=threshold, default_schema=schema,
                )
            return found
        except Exception:  # 보조 검사는 필수 경로를 막지 않는다
            logger.warning("stats_guard 검사 실패, 건너뜁니다", exc_info=True)
            return []

    async def _check_unrequested_columns(self, stmt: Any, question: str, schema: str | None = None) -> Any:
        """요구하지 않은 컬럼이 SELECT에 있는지 검사한다(question_guard 규칙).

        규칙이 등록돼 있지 않으면 아무 일도 하지 않는다 — 요구/조건 표지가 영어 관용구라
        언어·도메인마다 달라서, 코드에 박지 않고 관리자가 정하게 한다.
        """
        from pgxnl.agent.question_guard import (
            DEFAULT_ASK_MARKERS,
            DEFAULT_CONDITION_MARKERS,
            check_single_column,
        )

        if self._rule_store is None:
            return None
        try:
            rules = [
                r for r in await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
                if isinstance(r.definition, dict) and r.definition.get("kind") == "single_column"
            ]
            if not rules:
                return None
            ir = self._parser.to_ir(stmt)
            if ir is None:
                return None
            for rule in rules:
                found = check_single_column(
                    ir, question,
                    strict=bool(rule.definition.get("strict", True)),
                    ask_markers=tuple(rule.definition.get("ask") or DEFAULT_ASK_MARKERS),
                    condition_markers=tuple(
                        rule.definition.get("condition") or DEFAULT_CONDITION_MARKERS
                    ),
                )
                if found:
                    return found
            return None
        except Exception:  # 보조 검사는 필수 경로를 막지 않는다
            logger.warning("question_guard(single_column) 검사 실패, 건너뜁니다", exc_info=True)
            return None

    async def _emit_column_rationale(self, sql: str, question: str, emit_debug: Any) -> None:
        """SELECT 항목마다 "질문의 어느 구절이 이걸 요구했나"를 모델에게 묻고 디버그로 찍는다.

        디버그 전용이라 어떤 판정에도 관여하지 않는다 — LLM 호출이 하나 늘기 때문에
        debug=false인 평상시 경로에는 영향이 없다.

        인용은 **질문 원문에서 글자 그대로** 가져오게 하고, 실제로 있는지 코드가 확인해
        `✓`/`✗ 원문에 없음`으로 표시한다. 근거를 지어낸 경우를 눈으로 바로 가릴 수 있어야
        이 출력을 믿고 쓸 수 있다.
        """
        try:
            ir = self._parser.to_ir(self._parser.parse(sql))
            if ir is None or not ir.select_items:
                return
            prompt = RATIONALE_PROMPT
            # 이 단계에 프로필이 지정돼 있지 않으면 **react가 쓰는 모델**로 떨어진다.
            # `_llm_for`의 기본 폴백은 settings 기본 클라이언트인데, 단계별 프로필을
            # 쓰는 배포에서는 그쪽이 설정돼 있지 않을 수 있다(실측: .env의 watsonx CPD
            # 엔드포인트가 죽어 있어 디버그 출력이 통째로 사라졌다). 디버그 보조 기능이
            # 별도 설정을 요구하면 안 된다.
            llm = (
                self._llm_overrides.get("column_rationale")
                or self._llm_overrides.get("react")
                or self._llm
            )
            resp = await llm.complete(
                system_prompt=prompt,
                messages=[{"role": "user", "content": f"[질문]\n{question}\n\n[SQL]\n{sql}"}],
            )
            rows = parse_rationale(resp.text or "", question)
            if not rows:
                await emit_debug("컬럼 근거: 모델이 형식을 지키지 않아 해석하지 못했습니다")
                return
            await emit_debug(
                "컬럼 근거 (SELECT 항목 ↔ 질문 구절):\n"
                + "\n".join(r.debug_line() for r in rows)
            )
            if resp.usage:
                await emit_debug(f"컬럼 근거 토큰 사용량: {resp.usage}")
        except Exception:  # 디버그 표시가 질의를 죽이면 안 된다
            logger.warning("컬럼 근거 설명 실패, 건너뜁니다", exc_info=True)

    async def _check_missing_columns(self, stmt: Any, schema: str) -> list:
        """참조한 컬럼이 그 테이블에 없는지 검사한다(§missing_column).

        `_column_owners`가 만든 역인덱스를 재사용한다 — alias_fix 규칙이 등록돼 있으면
        이미 계산돼 스키마 캐시에 있으므로 추가 비용이 없다. 없으면 검사를 건너뛴다.
        """
        if self._rule_store is None:
            return []
        try:
            rule_defs = await self._rule_store.list_active(self._target_name, "canonicalization", schema=schema)
            owners = await self._column_owners(schema, rule_defs)
            if not owners:
                return []
            # 컬럼명 -> 소유 테이블 역인덱스를 테이블 -> 컬럼 집합으로 뒤집는다.
            by_table: dict[str, set[str]] = {}
            for column, tables in owners.items():
                for t in tables:
                    by_table.setdefault(t.lower(), set()).add(column)
            return find_missing_columns(stmt, columns_by_table=by_table, owners=owners)
        except Exception:  # 가드 실패는 질의를 죽일 사유가 아니다
            logger.warning("컬럼 존재 가드 실패, 건너뜁니다", exc_info=True)
            return []

    async def _resolve_column(self, table: str, col: str, schema: str) -> str | None:
        """IR이 소문자로 접어 준 컬럼명을 **실제 카탈로그 이름**으로 되돌린다.

        `frpm."School Type"`은 IR에서 `school type`으로 온다. 그대로 따옴표로 감싸
        조회하면 PostgreSQL이 대소문자를 구분해 `column "school type" does not exist`로
        실패한다 — 그러면 값 존재 확인이 조용히 "판단 불가"가 되어 검사가 무력해진다.
        """
        try:
            rows = await self._conn.execute_readonly(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = $1 AND lower(table_name) = lower($2)
                  AND lower(column_name) = lower($3) LIMIT 1
                """,
                params=[schema, table, col], timeout_seconds=10, schema=schema,
            )
        except Exception:
            return None
        return rows[0]["column_name"] if rows else None

    async def _emit_filter_rationale(self, sql: str, schema: str, emit_debug: Any) -> None:
        """WHERE의 필터 값이 그 컬럼에 **실제로 있는지** 데이터로 확인해 디버그로 찍는다.

        컬럼 선택 오류는 대부분 여기서 드러난다 — 실측(BIRD 445): 모델이
        `"School Type" = 'High Schools'`를 썼는데 그 컬럼의 실제 값은
        `'High Schools (Public)'`이다. 프롬프트에 값 목록이 있었는데도 틀렸고,
        디버그에는 그 사실이 안 보여 눈으로 찾아야 했다.

        LLM을 쓰지 않는다 — 파싱 + 대상 DB 조회뿐이라 `_emit_column_rationale`과 달리
        비용이 거의 없다. 디버그 전용이라 어떤 판정에도 관여하지 않는다.
        """
        from pgxnl.agent.question_guard import _filter_literals

        try:
            stmt = self._parser.parse(sql)
            ir = self._parser.to_ir(stmt)
            if ir is None:
                return
            alias_to_table = {
                a.lower(): t.rsplit(".", 1)[-1] for a, t in (stmt.alias_to_table or {}).items()
            }
            pairs = _filter_literals(ir.where) + _filter_literals(ir.having)
            out: list[str] = []
            seen: set[tuple[str, str]] = set()
            # _filter_literals 는 (값, 컬럼, 패턴 여부) 세 개를 준다 — 예전엔 두 개로 풀어
            # 디버그에서 "too many values to unpack" 으로 매번 죽었다(2026-10-12 수정).
            # LIKE 패턴은 값이 아니라 "그 값이 있나"를 셀 수 없으니 건너뛴다.
            for literal, column, is_pattern in pairs:
                if not column or is_pattern:
                    continue
                alias, _, name = column.rpartition(".")
                col = name.strip().strip('"')
                table = alias_to_table.get(alias.strip().strip('"').lower()) if alias else None
                if not table or not col or (table, literal) in seen:
                    continue
                seen.add((table, literal))
                real = await self._resolve_column(table, col, schema)
                if real is None:
                    out.append(f'    {table}."{col}"  →  그런 컬럼이 없습니다 ✗')
                    continue
                col = real
                try:
                    hit = await self._conn.execute_readonly(
                        f'SELECT count(*) AS n FROM "{table}" WHERE "{col}" = $1',
                        params=[literal], timeout_seconds=10, schema=schema,
                    )
                    n = hit[0]["n"] if hit else 0
                except Exception:  # 조회 실패는 판단 불가 — 그 줄만 건너뛴다
                    continue
                if n:
                    out.append(f'    {table}."{col}" = {literal!r}  →  {n:,}행 ✓')
                else:
                    near = await self._nearby_values(table, col, literal, schema)
                    hint = f"  (비슷한 값: {near})" if near else ""
                    out.append(f'    {table}."{col}" = {literal!r}  →  0행 ✗ 그 컬럼에 없는 값{hint}')
            if out:
                await emit_debug("필터 값 검증 (리터럴 ↔ 실제 데이터):\n" + "\n".join(out))
        except Exception:  # 디버그 표시가 질의를 죽이면 안 된다
            logger.warning("필터 값 검증 실패, 건너뜁니다", exc_info=True)

    async def _nearby_values(self, table: str, col: str, literal: str, schema: str) -> str:
        """같은 컬럼에서 그 값과 비슷한 실제 값 몇 개. 무엇을 썼어야 하는지 바로 보인다."""
        try:
            rows = await self._conn.execute_readonly(
                f'SELECT DISTINCT "{col}" AS v FROM "{table}" WHERE "{col}" ILIKE $1 LIMIT 3',
                params=[f"%{literal[:20]}%"], timeout_seconds=10, schema=schema,
            )
        except Exception:
            return ""
        return ", ".join(repr(r["v"]) for r in rows if r["v"] is not None)

    async def _check_redundant_joins(self, stmt: Any, schema: str) -> list:
        """필터에 기여하지 않는 조인을 지적한다(question_guard 규칙).

        판정에 쓰는 사본 맵은 `CanonicalColumnRule`이 쓰는 것과 같다 — 이미 계산해
        스키마 캐시에 넣어둔 값이라 추가 비용이 없다. 규칙(`{"kind": "redundant_join"}`)이
        등록돼 있지 않으면 아무 일도 하지 않는다.
        """
        if self._rule_store is None:
            return []
        try:
            rules = [
                r for r in await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
                if isinstance(r.definition, dict) and r.definition.get("kind") == "redundant_join"
            ]
            if not rules:
                return []
            canon_defs = await self._rule_store.list_active(self._target_name, "canonicalization", schema=schema)
            copies = await self._canonical_copies(schema, canon_defs)
            if not copies:
                return []
            ir = self._parser.to_ir(stmt)
            if ir is None:
                return []
            return find_redundant_joins(
                ir, alias_to_table=dict(stmt.alias_to_table or {}), copies=copies,
            )
        except Exception:  # 가드 실패는 질의를 죽일 사유가 아니다
            logger.warning("불필요 조인 가드 실패, 건너뜁니다", exc_info=True)
            return []

    async def _check_fanout_counts(self, stmt: Any, schema: str) -> list:
        """1:N 조인으로 부푼 COUNT(fanout_count 규칙, 2026-10-27). 규칙이 없으면 아무 일도 안 한다.

        유일성은 대상 DB 카탈로그로 본다 — 컬럼 하나짜리 UNIQUE 인덱스(PK 포함) 또는 n_distinct = -1.
        """
        if self._rule_store is None:
            return []
        try:
            rules = [
                r for r in await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
                if isinstance(r.definition, dict) and r.definition.get("kind") == "fanout_count"
            ]
            if not rules:
                return []
            ir = self._parser.to_ir(stmt)
            if ir is None:
                return []
            from pgxnl.agent.fanout_count import find_fanout_counts

            async def _is_unique(table: str, column: str) -> bool | None:
                # alias_to_table 은 `public.orders` 처럼 스키마를 붙인 채로 온다 — 붙어 있으면 그쪽을 따른다
                sch, _, name = table.replace('"', "").rpartition(".")
                rows = await self._conn.execute_readonly(
                    """
                    SELECT EXISTS (
                             SELECT 1 FROM pg_index i
                             JOIN pg_class c ON c.oid = i.indrelid
                             JOIN pg_namespace n ON n.oid = c.relnamespace
                             JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
                             WHERE i.indisunique AND i.indnkeyatts = 1 AND n.nspname = $1
                               AND lower(c.relname) = lower($2) AND lower(a.attname) = lower($3)
                           ) AS uniq,
                           (SELECT n_distinct FROM pg_stats
                             WHERE schemaname = $1 AND lower(tablename) = lower($2)
                               AND lower(attname) = lower($3) LIMIT 1) AS nd
                    """,
                    params=[sch or schema, name, column], timeout_seconds=15, schema=schema,
                )
                if not rows:
                    return None
                if rows[0]["uniq"] or rows[0]["nd"] == -1:
                    return True
                return False if rows[0]["nd"] is not None else None

            return await find_fanout_counts(
                ir, alias_to_table=dict(stmt.alias_to_table or {}), is_unique=_is_unique,
            )
        except Exception:  # 가드 실패는 질의를 죽일 사유가 아니다
            logger.warning("fanout_count 가드 실패, 건너뜁니다", exc_info=True)
            return []

    async def _check_grouped_rows(self, stmt: Any, question: str, schema: str) -> bool:
        """그룹별 집계만 여러 행 나오는 SQL(grouped_rows 규칙, 2026-10-16). 규칙이 없으면 아무 일도 안 한다."""
        if self._rule_store is None:
            return False
        try:
            rules = [
                r for r in await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
                if isinstance(r.definition, dict) and r.definition.get("kind") == "grouped_rows"
            ]
            if not rules:
                return False
            from pgxnl.agent.grouped_rows import find_grouped_rows
            return find_grouped_rows(stmt, question)
        except Exception:  # 가드 실패는 질의를 죽일 사유가 아니다
            logger.warning("grouped_rows 가드 실패, 건너뜁니다", exc_info=True)
            return False

    async def _check_per_group_top(self, stmt: Any, question: str, schema: str) -> bool:
        """그룹별 1위를 묻는데 LIMIT 1 로 자른 SQL(per_group_top 규칙, 2026-10-28). 규칙이 없으면 아무 일도 안 한다."""
        if self._rule_store is None:
            return False
        try:
            rules = [
                r for r in await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
                if isinstance(r.definition, dict) and r.definition.get("kind") == "per_group_top"
            ]
            if not rules:
                return False
            from pgxnl.agent.per_group_top import find_per_group_top
            return find_per_group_top(stmt, question)
        except Exception:  # 가드 실패는 질의를 죽일 사유가 아니다
            logger.warning("per_group_top 가드 실패, 건너뜁니다", exc_info=True)
            return False

    async def _check_column_rationale(self, stmt: Any, question: str, sql: str, schema: str | None = None) -> Any:
        """SELECT 항목마다 질문의 근거 구절을 받아, 근거 없는 항목을 지목한다.

        규칙(`{"kind": "column_rationale"}`)이 없으면 아무 일도 하지 않는다 — LLM 호출이
        하나 늘어나므로(질의당 약 4초) 켤지 말지는 관리자가 정한다.

        판정이 LLM이라 결정론적이 아니다. 그래서 조언으로만 돌려준다 —
        `advised`가 한 번만 알리게 막아, 모델이 그대로 두기로 하면 같은 SQL이 다시 와
        중복 가드가 finalize로 보낸다.
        """
        if self._rule_store is None:
            return None
        try:
            rules = [
                r for r in await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
                if isinstance(r.definition, dict) and r.definition.get("kind") == "column_rationale"
            ]
            if not rules:
                return None
            ir = self._parser.to_ir(stmt)
            if ir is None or not ir.select_items:
                return None
            llm = (
                self._llm_overrides.get("column_rationale")
                or self._llm_overrides.get("react")
                or self._llm
            )
            resp = await asyncio.wait_for(
                llm.complete(
                    system_prompt=RATIONALE_PROMPT,
                    messages=[{"role": "user", "content": f"[질문]\n{question}\n\n[SQL]\n{sql}"}],
                ),
                timeout=RATIONALE_TIMEOUT_SECONDS,
            )
            rows = parse_rationale(resp.text or "", question)
            return find_unsupported(rows, select_count=len(ir.select_items))
        except Exception:  # 가드 실패는 질의를 죽일 사유가 아니다
            logger.warning("컬럼 근거 가드 실패, 건너뜁니다", exc_info=True)
            return None

    async def _check_ambiguous_columns(self, stmt: Any, schema: str) -> list:
        """필터 값이 여러 컬럼에서 흔한 값인지 검사한다(stats_guard 규칙).

        후보는 pg_stats의 최빈값에서 찾는다 — 대상 DB에 질의 한 번이면 끝난다.
        규칙(`{"kind": "ambiguous_column"}`)이 등록돼 있지 않으면 아무 일도 하지 않는다.
        """
        if self._rule_store is None:
            return []
        try:
            rules = [
                r for r in await self._rule_store.list_advisory_guards(self._target_name, schema=schema)
                if isinstance(r.definition, dict) and r.definition.get("kind") == "ambiguous_column"
            ]
            if not rules:
                return []
            ir = self._parser.to_ir(stmt)
            if ir is None:
                return []

            async def _columns_with_value(sch: str, value: str) -> list[str]:
                rows = await self._conn.execute_readonly(
                    """
                    SELECT tablename, attname FROM pg_stats
                    WHERE schemaname = $1 AND most_common_vals IS NOT NULL
                      AND $2 = ANY(most_common_vals::text::text[])
                    """,
                    params=[sch, value], timeout_seconds=15, schema=sch,
                )
                return [f"{r['tablename']}.{r['attname']}" for r in rows]

            return await check_ambiguous_columns(
                ir, alias_to_table=stmt.alias_to_table, lookup=_columns_with_value,
                schema=schema,
                min_length=int(rules[0].definition.get("min_length", 4)),
            )
        except Exception:  # 보조 검사는 필수 경로를 막지 않는다
            logger.warning("ambiguous_column 검사 실패, 건너뜁니다", exc_info=True)
            return []

    async def _drop_real_values(self, mutations: list, stmt: Any, schema: str) -> list:
        """대상 컬럼에 실제로 존재하는 값은 "변형"이 아니므로 신고 목록에서 뺀다.

        리터럴 가드는 텍스트 유사도만 본다. 그래서 스키마의 **열거값**을 질문의 자연어와
        비교하게 되면 방향이 거꾸로 뒤집힌다 — 실측(BIRD 445):

            'High Schools (Public)'                   유사도 0.78 -> 걸림  (gold의 값, 1331행)
            'High Schools In 1 School Dist. (Public)' 유사도 0.58 -> 통과  (오답, 1행)

        맞는 값만 막고 틀린 값은 통과시켰고, 질문에 없는 문자열을 쓰라고 요구하니 모델이
        따를 방법이 없어 20회 반복 끝에 타임아웃했다. 값의 **존재 여부**는 데이터로
        확정할 수 있으므로 그걸로 가른다(질문 텍스트만 보는 `question_guard`가 아니라
        여기서 하는 이유다 — 그 모듈은 데이터를 조회하지 않는다는 제약이 있다).

        확인할 수 없으면(컬럼 미상, 조회 실패) 원래 판정을 그대로 둔다 — 판단 불가는
        신고를 지울 근거가 아니다.
        """
        if not mutations:
            return mutations
        alias_to_table = {
            a.lower(): t.rsplit(".", 1)[-1] for a, t in (stmt.alias_to_table or {}).items()
        }
        kept = []
        for m in mutations:
            column = getattr(m, "column", None)
            table = col = None
            if column:
                alias, _, name = column.rpartition(".")
                col = name.strip().strip('"') or None
                table = alias_to_table.get(alias.strip().strip('"').lower()) if alias else None
            if not table or not col:
                kept.append(m)
                continue
            # IR은 컬럼명을 소문자로 접는다. 실제 이름으로 되돌리지 않으면 따옴표 컬럼
            # (`"School Type"`)에서 조회가 실패해 이 검사가 조용히 무력해진다.
            real = await self._resolve_column(table, col, schema)
            if real is None:
                kept.append(m)
                continue
            col = real
            try:
                rows = await self._conn.execute_readonly(
                    f'SELECT 1 FROM "{table}" WHERE "{col}" = $1 LIMIT 1',
                    params=[m.literal], timeout_seconds=10, schema=schema,
                )
            except Exception:  # 조회 실패는 판단 불가
                logger.debug("리터럴 실재 확인 실패: %s.%s", table, col, exc_info=True)
                kept.append(m)
                continue
            if not rows:
                kept.append(m)  # 그런 값이 없다 — 변형이 맞다
        return kept

    def _check_question_literals(self, stmt: Any, question: str, quote_source: str | None = None) -> list:
        """질문의 필터 값을 변형했는지 검사한다. IR 추출이 실패해도 조용히 넘어간다 —
        보조 검사가 필수 경로(SQL 생성)를 막으면 안 된다(설계 원칙 1).

        `quote_source` 는 evidence 를 붙이기 전의 질문이다. 따옴표 값은 여기서만 뽑는다 — evidence 의
        따옴표 값까지 보면 질문과 evidence 가 다를 때 evidence 쪽 표기가 "따로 주어진 값"으로 통과한다
        (codebase_community 316, 2026-10-14)."""
        from pgxnl.agent.question_guard import check_literals

        try:
            ir = self._parser.to_ir(stmt)
            return check_literals(ir, question, quote_source=quote_source) if ir is not None else []
        except Exception:
            logger.debug("리터럴 검사 실패 — 건너뜁니다", exc_info=True)
            return []

    async def _column_owners(self, schema: str, rule_defs: list) -> dict[str, set[str]] | None:
        """`컬럼명 -> {소유 테이블}` 역인덱스. AliasFixRule이 잘못된 별칭을 고치는 데 쓴다.

        alias_fix 규칙이 등록돼 있을 때만 만든다 — 스키마 introspection이 대상 DB에
        쿼리를 날리므로, 쓰지도 않을 걸 매 질의마다 조회하면 낭비다. 결과는 스키마
        캐시에 넣어 테이블 수만큼의 describe_table 호출이 반복되지 않게 한다.
        """
        if not any(
            r.rule_type == "canonicalization"
            and isinstance(r.definition, dict)
            and r.definition.get("kind") == "alias_fix"
            for r in rule_defs
        ):
            return None

        cache_key = f"colowners:{schema}"
        if self._schema_cache is not None:
            cached = await self._schema_cache.get(self._target_name, cache_key)
            if cached:
                return {col: set(tables) for col, tables in cached.items()}

        metas = [
            await self._conn.describe_table(schema, t.name)
            for t in await self._conn.list_tables(schema)
        ]
        owners = build_column_owners(metas)
        if self._schema_cache is not None:
            await self._schema_cache.set(
                self._target_name, cache_key, {col: sorted(t) for col, t in owners.items()}
            )
        return owners

    async def _pk_columns(self, schema: str, rule_defs: list) -> dict[str, set[str]] | None:
        """`테이블 -> {PK 컬럼}`. DistinctSingleColumnRule 이 PK 컬럼에는 DISTINCT 를 붙이지 않는 데
        쓴다(2026-10-06). 그 규칙이 있을 때만 만들고 스키마 캐시에 둔다(`_column_owners` 와 같은 방식)."""
        if not any(
            r.rule_type == "canonicalization"
            and isinstance(r.definition, dict)
            and r.definition.get("kind") == "distinct_single_column"
            for r in rule_defs
        ):
            return None
        cache_key = f"pkcols:{schema}"
        if self._schema_cache is not None:
            cached = await self._schema_cache.get(self._target_name, cache_key)
            if cached:
                return {t: set(cols) for t, cols in cached.items()}
        pks: dict[str, set[str]] = {}
        for t in await self._conn.list_tables(schema):
            meta = await self._conn.describe_table(schema, t.name)
            pks[meta.name.lower()] = {c.name.lower() for c in meta.columns if c.is_primary_key}
        if self._schema_cache is not None:
            await self._schema_cache.set(self._target_name, cache_key, {t: sorted(c) for t, c in pks.items()})
        return pks

    async def _timestamp_columns(self, schema: str, rule_defs: list) -> dict[str, set[str]] | None:
        """`테이블 -> {timestamp 컬럼}`. DateLiteralCompareRule 이 timestamp 컬럼에만 DATE() 를 씌우는 데
        쓴다(2026-10-14). 그 규칙이 있을 때만 만들고 스키마 캐시에 둔다(`_pk_columns` 와 같은 방식)."""
        if not any(
            r.rule_type == "canonicalization"
            and isinstance(r.definition, dict)
            and r.definition.get("kind") == "date_literal_compare"
            for r in rule_defs
        ):
            return None
        cache_key = f"tscols:{schema}"
        if self._schema_cache is not None:
            cached = await self._schema_cache.get(self._target_name, cache_key)
            if cached:
                return {t: set(cols) for t, cols in cached.items()}
        found: dict[str, set[str]] = {}
        for t in await self._conn.list_tables(schema):
            meta = await self._conn.describe_table(schema, t.name)
            found[meta.name.lower()] = {
                c.name.lower() for c in meta.columns if (c.data_type or "").lower().startswith("timestamp")
            }
        if self._schema_cache is not None:
            await self._schema_cache.set(self._target_name, cache_key, {t: sorted(c) for t, c in found.items()})
        return found

    async def _canonical_copies(
        self, schema: str, rule_defs: list
    ) -> dict[tuple[str, str], tuple[str, str]] | None:
        """`(사본테이블, 사본컬럼) -> (정본테이블, 정본컬럼)`. CanonicalColumnRule이 쓴다.

        Design Lab이 데이터를 훑어 만든 판정이라 비싸다 — `canonical_column` 규칙이
        등록돼 있을 때만 계산하고, 스키마 캐시에 넣어 질의마다 재분석하지 않는다
        (`_column_owners`와 같은 방식). 데이터가 바뀌면 캐시를 비워야 판정이 갱신된다.
        """
        canon_rule = next(
            (
                r for r in rule_defs
                if r.rule_type == "canonicalization"
                and isinstance(r.definition, dict)
                and r.definition.get("kind") == "canonical_column"
            ),
            None,
        )
        if canon_rule is None:
            return None

        # 개념 별칭 — 이름 표기가 달라 자동으로는 안 묶이는 사본을 규칙 정의로 알려준다.
        # `find_duplicate_concepts`는 이름을 정규화해 묶는데, `charterfundingtype`과
        # `fundingtype`은 그렇게 갈린다(끝의 name/nm만 떼므로). 실제로는 같은 개념이고
        # schools 쪽이 정본이다 — frpm이 값을 가진 행은 전부 schools에도 있고 역은 아니다.
        aliases = canon_rule.definition.get("aliases")
        concept_aliases = (
            {str(k): str(v) for k, v in aliases.items()} if isinstance(aliases, dict) else None
        )

        # 캐시 키에 별칭을 반영한다 — 규칙을 고쳐도 옛 판정이 남아 있으면 변경이 묻힌다.
        alias_sig = ",".join(f"{k}={v}" for k, v in sorted((concept_aliases or {}).items()))
        cache_key = f"canoncopies:{schema}:{alias_sig}" if alias_sig else f"canoncopies:{schema}"
        if self._schema_cache is not None:
            cached = await self._schema_cache.get(self._target_name, cache_key)
            if cached is not None:
                # 캐시는 4원소 리스트의 배열이다 — dict 키에 구분자를 끼워 넣으면
                # NUL 같은 문자를 PostgreSQL 텍스트에 저장할 수 없다.
                return {(t, c): (ct, cc) for t, c, ct, cc in cached}

        from pgxnl.agent.designlab import analyze_schema

        try:
            report = await analyze_schema(
                self, target_name=self._target_name, schema=schema, concept_aliases=concept_aliases,
            )
        except Exception:  # noqa: BLE001 — 분석 실패는 교정을 건너뛸 사유이지 질의를 죽일 사유가 아니다
            logger.warning("Design Lab 분석 실패, 정본 교정을 건너뜁니다", exc_info=True)
            return None

        copies: dict[tuple[str, str], tuple[str, str]] = {}
        for dup in report.duplicate_concepts:
            if not dup.canonical or not dup.divergences:
                continue
            if max(d[4] for d in dup.divergences) <= 0:
                continue  # 값이 같으면 어느 쪽을 써도 결과가 같다 — 고칠 이유가 없다
            ct, cc = dup.canonical.split(".", 1)
            for table, column in dup.columns:
                if f"{table}.{column}" != dup.canonical:
                    copies[(table.lower(), column.lower())] = (ct, cc)
        if self._schema_cache is not None:
            await self._schema_cache.set(
                self._target_name, cache_key,
                [[t, c, ct, cc] for (t, c), (ct, cc) in copies.items()],
            )
        return copies

    async def _validate(self, sql: str, *, user_id: int, question: str, schema: str = "public"):
        validator = SqlValidator(
            self._parser, self._conn, self._glossary_store, max_cost=self._settings.validation_max_cost,
            target_name=self._target_name, schema_cache=self._schema_cache, default_schema=schema,
        )
        result = await validator.validate(sql, user_id=user_id)
        if self._settings.audit_log_enabled and self._system_pool is not None:
            await record_audit_log(
                self._system_pool, target_name=self._target_name, user_id=user_id, question=question,
                sql=sql, decision=result.decision, reason=result.reason, estimated_cost=result.estimated_cost,
            )
        return result

    async def _summarize(self, question: str, rows: list[dict]) -> tuple[str, dict[str, int] | None]:
        resp = await self._llm_for("summarize").complete(
            system_prompt="아래 질문과 SQL 실행 결과를 바탕으로 간결한 한국어 답변을 작성하세요.",
            messages=[{"role": "user", "content": f"질문: {question}\n결과: {rows[:20]}"}],
        )
        return resp.text or "", resp.usage


def to_mschema_from_candidate(candidate: Any) -> str:
    return candidate.mschema if isinstance(candidate.mschema, str) else str(candidate.mschema)


def _glossary_label(entry: GlossaryEntry) -> str:
    """용어집 한 줄의 라벨. term이 컬럼명과 다르면 **term을 앞에** 두고 컬럼을 잇는다.

    용어집이 하는 일은 "질문이 이렇게 말하면 이 컬럼"이라 방향이 term -> 컬럼이다.
    컬럼을 앞에 두면 모델이 컬럼 목록을 훑고 나서야 표현을 만나 방향이 뒤집힌다.
    term이 컬럼명과 같은 항목(25건 중 19건)은 화살표가 무의미하므로 이름만 쓴다.

    term에 따옴표를 두르지 않는다 — 프롬프트에서 따옴표는 SQL 리터럴을 연상시켜,
    질문 표현을 값으로 오해할 여지를 만든다.
    """
    col, term = entry.column_name, entry.term
    if col and term and term.strip().lower() != col.strip().lower():
        return f"{term} -> {col}"
    return col or term


def _limit_glossary(
    terms: list[GlossaryEntry], question: str, threshold_chars: int
) -> list[GlossaryEntry]:
    """용어집이 threshold를 넘을 때만 질문 관련성으로 거른다.

    **항상 거르면 안 된다는 걸 실측으로 확인했다**(2026-09-03, BIRD
    california_schools 30문항). 질문당 용어집을 1,761자 -> 165자로 줄이자 EX가
    19.7(6회) -> 15.0(4회)으로 떨어졌는데, 깨진 443/448/449는 **용어집을 0자 받는**
    문항이었다. 즉 DOC/SOC 같은 내용이 도움이 된 게 아니라 schema_context가 길다는
    사실 자체가 모델을 붙들고 있었다(셋 다 실패 양상이 "묻지 않은 컬럼/조건을
    덧붙임"으로 일치). 지금 규모에서는 거를 이유가 없다.

    그래도 필터를 지우지 않는 이유는 §5.11의 원래 문제가 진짜이기 때문이다 —
    용어집이 수십 개로 늘면 질문과 무관한 정의가 프롬프트를 압도한다. 그때만
    작동하는 안전장치로 둔다.
    """
    if sum(len(t.definition) for t in terms) <= threshold_chars:
        return terms
    return [t for t in terms if _glossary_relevant(question, t)]


def _glossary_relevant(question: str, entry: GlossaryEntry) -> bool:
    """§5.11 필터. 판정 규칙 자체는 `governance.glossary_terms`에 있다 — 등록 시점
    (관리 API의 진단)과 사용 시점이 같은 규칙을 봐야 "등록은 됐는데 어떤 질문에도
    안 실리는" 항목이 조용히 생기지 않는다."""
    return is_relevant(question, entry.term, entry.column_name, entry.definition)


def _format_generation_constraint(definition: dict[str, Any]) -> str:
    """rule_type='generation_constraint'의 definition은 {"text": "..."} 관례를 따른다.
    str(dict)로 그대로 넣으면 프롬프트에 "{'text': '...'}"처럼 Python dict repr이
    그대로 노출돼 지저분하다 — text 값만 뽑아서 자연스러운 문장으로 넣는다. text 키가
    없는(관례를 안 지킨) definition은 안전하게 str(dict)로 폴백한다."""
    text = definition.get("text")
    return text if isinstance(text, str) else str(definition)


def _format_few_shot(definition: dict[str, Any]) -> str:
    """rule_type='few_shot'의 definition({question, good_sql, bad_sql?, explanation?})을
    프롬프트에 넣을 텍스트 블록으로 만든다. bad_sql/explanation은 대비를 통해 경계
    조건(예: "이 케이스는 되고 저 케이스는 안 된다")을 보여주는 용도라 선택 사항이다."""
    lines = [f"질문: {definition.get('question', '')}", f"좋은 SQL: {definition.get('good_sql', '')}"]
    if definition.get("bad_sql"):
        lines.append(f"나쁜 SQL (하지 말 것): {definition['bad_sql']}")
    if definition.get("explanation"):
        lines.append(f"이유: {definition['explanation']}")
    return "\n".join(lines)
