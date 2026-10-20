"""인증 API. design 문서 §9 참고."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from pgxnl.auth.dependencies import CurrentUser, get_current_user

router = APIRouter(prefix="/api", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(req: LoginRequest):
    from pgxnl.api.state import state

    if state.user_store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "인증 서비스가 아직 초기화되지 않았습니다")

    api_key = await state.user_store.get_api_key_by_credentials(req.username, req.password)
    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "아이디 또는 비밀번호가 올바르지 않습니다")
    return {"api_key": api_key}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}


def _require_user_store():
    from pgxnl.api.state import state

    if state.user_store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "시스템 DB 미연결 — 사용자 관리를 사용할 수 없습니다")
    return state.user_store


@router.get("/me/credentials")
async def list_my_credentials(user: CurrentUser = Depends(get_current_user)):
    store = _require_user_store()
    creds = await store.list_credentials(user.id)
    return {
        "credentials": [
            {"target_name": c.target_name, "db_username": c.db_username, "updated_at": c.updated_at.isoformat()}
            for c in creds
        ]
    }


class CredentialBody(BaseModel):
    db_username: str
    db_password: str


@router.put("/me/credentials/{target}")
async def set_my_credential(target: str, body: CredentialBody, user: CurrentUser = Depends(get_current_user)):
    from pgxnl.api.state import state

    store = _require_user_store()
    await store.set_credential(user.id, target, body.db_username, body.db_password)
    state.invalidate_user_orchestrator(user.id, target)
    return {"ok": True, "target": target}


@router.delete("/me/credentials/{target}")
async def delete_my_credential(target: str, user: CurrentUser = Depends(get_current_user)):
    from pgxnl.api.state import state

    store = _require_user_store()
    await store.delete_credential(user.id, target)
    state.invalidate_user_orchestrator(user.id, target)
    return {"ok": True, "target": target}


def _require_llm_profile_store():
    from pgxnl.api.state import state

    if state.llm_profile_store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "시스템 DB 미연결")
    return state.llm_profile_store


@router.get("/me/model-stage-config")
async def get_my_model_stage_config(user: CurrentUser = Depends(get_current_user)):
    """단계별 모델 개인 설정 — 관리자가 등록한 모델 목록(읽기 전용)과 내 현재 선택,
    그리고 지정 안 했을 때 적용되는 관리자 기본값을 함께 반환한다."""
    from pgxnl.api.llm_profiles import STAGE_LABELS

    store = _require_llm_profile_store()
    models = await store.list_profiles()
    admin_config = await store.get_stage_config()
    my_config = await store.get_user_stage_config(user.id)
    default_profile = await store.get_default_profile()
    profiles = {p.id: p for p in models}

    def _model_label(profile_id: int | None) -> str | None:
        if profile_id is None or profile_id not in profiles:
            return None
        p = profiles[profile_id]
        return f"{p.provider}/{p.model} ({p.name})"

    default_fallback_label = (
        f"{default_profile.provider}/{default_profile.model} ({default_profile.name})" if default_profile
        else "시스템 기본 모델"
    )

    return {
        "models": [
            {"id": p.id, "name": p.name, "provider": p.provider, "model": p.model}
            for p in models
        ],
        "stages": [
            {
                "stage": stage, "label": STAGE_LABELS[stage], "profile_id": my_config[stage],
                "admin_default_label": (
                    _model_label(admin_config.get(stage, {}).get("profile_id")) or default_fallback_label
                ),
            }
            for stage in my_config
        ],
    }


class StageAssignBody(BaseModel):
    stage: str
    profile_id: int | None = None


@router.put("/me/model-stage-config")
async def set_my_model_stage_config(body: StageAssignBody, user: CurrentUser = Depends(get_current_user)):
    from pgxnl.api.state import state

    store = _require_llm_profile_store()
    try:
        await store.set_user_stage_profile(user.id, body.stage, body.profile_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    state.invalidate_user_orchestrators_all(user.id)
    return {"ok": True}


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/me/change-password")
async def change_password(body: ChangePasswordBody, user: CurrentUser = Depends(get_current_user)):
    store = _require_user_store()
    ok = await store.get_api_key_by_credentials(user.username, body.current_password)
    if ok is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "현재 비밀번호가 올바르지 않습니다")
    await store.set_password(user.id, body.new_password)
    return {"ok": True}
