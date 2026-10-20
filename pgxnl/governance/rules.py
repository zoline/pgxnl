"""SQL 생성/Canonicalization 규칙 레지스트리. design 문서 §5.11 참고.

명시적으로 등록된 규칙은 자동 추론 결과(discovery/join_history.py 등)보다 항상
우선(override)한다. target_name이 NULL이면 전역 규칙으로 취급한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import asyncpg

# stats_guard: 생성된 SQL을 **컬럼 통계**와 대조해 ReAct 루프에 관찰을 돌려준다
# (agent/stats_guard.py). 용어집이 아니라 여기 있는 이유는, 관리 대상이 낱말의 뜻이
# 아니라 판정 정책(임계값·발동 낱말·되돌릴 문구)이기 때문이다.
# question_guard: 생성된 SQL을 **질문 텍스트**와 대조한다(stats_guard와 근거가 다르다 —
# 이쪽은 데이터를 안 보므로 비용이 0이고 데이터가 바뀌어도 낡지 않는다).
# canonical_rewrite: 생성이 끝난 SQL을 **예시 쌍(나쁜 SQL -> 좋은 SQL)** 으로 고친다.
# canonicalization과 자리는 같지만(루프 뒤) 판정 주체가 다르다 — 저쪽은 파서, 이쪽은
# LLM이다. 파서로 판정할 수 있으면 canonicalization을 쓴다(확실한 걸 불확실하게 만들
# 이유가 없다). 이 분류는 **파서로는 못 정하는데 SQL만 보면 사람은 아는** 변환을 위한
# 것이고, 코드를 안 짜고 행 추가만으로 늘릴 수 있다는 게 존재 이유다.
# 프롬프트 앞이 아니라 뒤에 두는 이유는 [[general_front_exception_back]] — 예외를 앞에
# 두면 30문항 전부에서 저울질이 일어나 무관한 문항이 깨진다(2026-09-10 실측 -3).
# advisory_guard: 생성된 SQL을 보고 **관찰을 ReAct 루프에 돌려주는** 가드.
# `stats_guard`(근거=컬럼 통계)와 `question_guard`(근거=질문 텍스트)를 하나로 합친
# 것이다 — 둘을 가르던 "근거가 데이터냐 질문이냐"는 축은 사용자에게 의미가 없었다.
# 하는 일이 "루프에 조언을 돌려준다"로 같고, 정작 중요한 축(고칠 때까지 되돌리는가,
# 한 번만 알리는가)은 그 분류로 표현되지 않았다. `definition.kind`로 검사를 고른다.
# 구 두 이름은 읽기만 지원한다(이행 전 데이터를 위해).
RuleType = Literal[
    "canonicalization", "canonical_rewrite", "generation_constraint", "few_shot",
    "advisory_guard", "stats_guard", "question_guard",
]

#: 조언형 가드의 구 분류 이름들. `SqlRuleStore.list_advisory_guards()`가 함께 읽는다.
LEGACY_GUARD_TYPES = ("stats_guard", "question_guard")


@dataclass
class Rule:
    id: int
    target_name: str | None
    rule_type: RuleType
    definition: dict[str, Any]
    enabled: bool
    updated_at: datetime
    #: 이 대상 DB 안의 한 스키마에만 적용(2026-10-06). NULL 이면 대상 전체(또는 전역).
    #: BIRD 처럼 대상 하나에 스키마가 여러 개면 california_schools 의 컬럼 매핑이 card_games
    #: 질문에도 걸렸다 — 스키마의 테이블·컬럼을 언급하는 규칙만 여기에 묶는다.
    schema_name: str | None = None


class SqlRuleStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_active(
        self, target_name: str, rule_type: RuleType | None = None, *, schema: str | None = None,
    ) -> list[Rule]:
        """전역 + 이 대상 + (schema 를 주면) 이 대상의 그 스키마 규칙. schema 를 모르는 호출은
        스키마 전용 규칙을 받지 않는다 — 어느 스키마의 것인지 판단할 수 없기 때문이다."""
        query = """
            SELECT id, target_name, rule_type, definition, enabled, updated_at, schema_name
            FROM pgxnl_rules
            WHERE enabled AND (target_name = $1 OR target_name IS NULL)
              AND (schema_name IS NULL OR schema_name = $2)
        """
        params: list[Any] = [target_name, schema]
        if rule_type:
            query += " AND rule_type = $3"
            params.append(rule_type)
        # 규칙은 프롬프트에 번호 매긴 목록으로 들어간다 — 순서가 곧 내용이다. ORDER BY가
        # 없으면 PostgreSQL의 힙 순서를 따르는데, UPDATE된 행은 힙 끝으로 옮겨간다:
        # **규칙 하나를 고칠 때마다 그 규칙이 목록 맨 뒤로 이동한다.** 내용 변경의 효과를
        # 재려 해도 위치 변경이 섞여 원인 귀속이 안 된다(실측: 활성 7건이 id 순이 아니라
        # 13,22,21,4,6,7,12 순으로 나왔다). id 순으로 고정해 이 변수를 없앤다.
        query += " ORDER BY id"
        rows = await self._pool.fetch(query, *params)
        return [Rule(**dict(r)) for r in rows]

    async def list_all(self) -> list[Rule]:
        rows = await self._pool.fetch(
            "SELECT id, target_name, rule_type, definition, enabled, updated_at, schema_name FROM pgxnl_rules ORDER BY id"
        )
        return [Rule(**dict(r)) for r in rows]

    async def list_advisory_guards(self, target_name: str, *, schema: str | None = None) -> list[Rule]:
        """조언형 가드를 `advisory_guard` 와 구 분류(`stats_guard`/`question_guard`)에서
        함께 읽는다. 이행 중에도 양쪽이 동작하도록 한 것이고, 구 행이 모두 옮겨지면
        `LEGACY_GUARD_TYPES` 를 비우면 된다."""
        rows = await self._pool.fetch(
            """
            SELECT id, target_name, rule_type, definition, enabled, updated_at, schema_name
            FROM pgxnl_rules
            WHERE enabled AND (target_name = $1 OR target_name IS NULL)
              AND (schema_name IS NULL OR schema_name = $3)
              AND rule_type = ANY($2::text[])
            ORDER BY id
            """,
            target_name, ["advisory_guard", *LEGACY_GUARD_TYPES], schema,
        )
        return [Rule(**dict(r)) for r in rows]

    async def create(
        self, target_name: str | None, rule_type: RuleType, definition: dict[str, Any],
        schema_name: str | None = None,
    ) -> int:
        if schema_name and not target_name:
            raise ValueError("스키마 전용 규칙은 대상 DB 를 지정해야 합니다")
        row = await self._pool.fetchrow(
            """
            INSERT INTO pgxnl_rules (target_name, rule_type, definition, schema_name)
            VALUES ($1, $2, $3, $4) RETURNING id
            """,
            target_name, rule_type, definition, schema_name or None,
        )
        return row["id"]

    async def update(self, rule_id: int, *, definition: dict[str, Any] | None = None, enabled: bool | None = None) -> None:
        if definition is not None:
            await self._pool.execute(
                "UPDATE pgxnl_rules SET definition=$1, updated_at=now() WHERE id=$2", definition, rule_id
            )
        if enabled is not None:
            await self._pool.execute(
                "UPDATE pgxnl_rules SET enabled=$1, updated_at=now() WHERE id=$2", enabled, rule_id
            )

    async def delete(self, rule_id: int) -> None:
        await self._pool.execute("DELETE FROM pgxnl_rules WHERE id=$1", rule_id)
