"""기준 정보(seed) 내보내기·가져오기가 같이 쓰는 표 정의.

표마다 내보낼 열, 같은 항목을 알아보는 자연 키, 어떤 행을 내보낼지(대상 조건)를 둔다.
id 는 문서·기록이 "규칙 44"처럼 번호로 부르므로 함께 내보내고, 가져올 때 비어 있으면 그 번호를 쓴다.
LLM 프로필(pgxnl_llm_profiles)과 단계 설정은 API 키·환경 의존이라 다루지 않는다.
"""
from __future__ import annotations

from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"

# 내보낼 대상: 전역(target_name NULL) + 이 이름들
DEFAULT_TARGETS = ("BIRD",)

TABLES: dict[str, dict] = {
    "rules": {
        "table": "pgxnl_rules",
        "columns": ["id", "target_name", "schema_name", "rule_type", "definition", "enabled"],
        "jsonb": {"definition"},
        "key": ["target_name", "schema_name", "rule_type", "definition"],
        "nullable_target": True,
    },
    "glossary": {
        "table": "pgxnl_glossary",
        "columns": ["id", "target_name", "schema_name", "term", "table_name", "column_name",
                    "definition", "is_pii", "source", "scope"],
        "jsonb": set(),
        "key": ["target_name", "schema_name", "term", "table_name", "column_name"],
        "nullable_target": True,
    },
    "join_graph": {
        "table": "pgxnl_join_candidates",
        "columns": ["id", "target_name", "schema_name", "table_a", "column_a", "table_b", "column_b",
                    "source", "confidence", "calls", "reviewed"],
        "jsonb": set(),
        "key": ["target_name", "schema_name", "table_a", "column_a", "table_b", "column_b"],
        "nullable_target": False,
    },
    "gold_defects": {
        "table": "pgxnl_eval_gold_defects",
        "columns": ["id", "target_name", "db_id", "question_id", "reason", "evidence"],
        "jsonb": set(),
        "key": ["target_name", "db_id", "question_id"],
        "nullable_target": False,
    },
}
