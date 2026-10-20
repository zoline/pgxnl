"""FastAPI 의존성: X-API-Key 헤더 또는 ?api_key= 쿼리 파라미터로 인증.

design 문서 §5.13, §9 참고. SSE(EventSource)는 커스텀 헤더를 지원하지 않으므로
쿼리 파라미터 경로를 함께 허용한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status


@dataclass
class CurrentUser:
    id: int
    username: str
    role: str


async def get_current_user(request: Request) -> CurrentUser:
    api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
    if not api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API 키가 필요합니다")

    from pgxnl.api.state import state  # 순환참조 방지용 지연 임포트

    if state.user_store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "인증 서비스가 아직 초기화되지 않았습니다")

    record = await state.user_store.get_by_api_key(api_key)
    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 API 키입니다")

    return CurrentUser(id=record.id, username=record.username, role=record.role)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "관리자 권한이 필요합니다")
    return user
