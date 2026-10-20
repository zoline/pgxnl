"""임베딩 함수 타입.

design 문서 §5.6 참고. Schema RAG(§5.4), 문서 지식 레이어(§5.10), 하이브리드 캐시(§5.12),
사용례 순위가 공용으로 쓴다. 설정은 시스템 DB(`pgxnl.llm.embedding_config`)에 있고,
설정이 없으면 embed_fn 이 None 이라 관련 기능 전체가 꺼진다(§2.1 필수/보조 원칙).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

EmbedFn = Callable[[str], Awaitable[list[float]]]
