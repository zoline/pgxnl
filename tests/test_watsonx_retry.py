"""watsonx 재시도 판정 테스트.

배경(2026-09-02 실측): CPD 게이트웨이가 backend 5xx를 4xx로 감싸서 돌려준다.

    403 {"code":"user_authorization_failed",
         "message":"Failed to find the ... member in project_id ... Error 502 - Bad Gateway"}

상태코드만 보면 인증 실패라 즉시 포기해야 하지만 본문은 502 게이트웨이 장애다. 이걸
재시도하지 않아 BIRD 평가 30문항 중 15문항이 통째로 실패했다(run 120·121 폐기).
"""
from __future__ import annotations

import pytest

from pgxnl.llm.watsonx_client import _is_retryable

_REAL_403 = (
    '{"errors":[{"code":"user_authorization_failed","message":"Failed to find the 1000331010 '
    'member in project_id 4d97d812-8315-47dd-9c2a-bef42589338c Error 502 - Bad Gateway"}],'
    '"status_code":403}'
)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_is_retryable(status):
    assert _is_retryable(status, "")


def test_real_world_403_wrapping_502_is_retryable():
    """실제로 관측된 응답 — 이것 때문에 이 로직이 존재한다."""
    assert _is_retryable(403, _REAL_403)


@pytest.mark.parametrize(
    "body",
    ["Bad Gateway", "bad  gateway", "Gateway Timeout", "Service Unavailable", "upstream returned 503"],
)
def test_gateway_wording_in_body_makes_4xx_retryable(body):
    assert _is_retryable(403, body)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_plain_4xx_is_not_retryable(status):
    """진짜 인증·요청 오류는 재시도해도 같은 결과다 — 즉시 실패시켜야 한다."""
    assert not _is_retryable(status, '{"code":"invalid_request","message":"model_id not found"}')


def test_empty_body_4xx_is_not_retryable():
    assert not _is_retryable(401, "")
    assert not _is_retryable(401, None)


def test_success_is_not_retryable():
    assert not _is_retryable(200, "")
    assert not _is_retryable(204, "Bad Gateway")  # 본문이 뭐든 성공은 재시도 대상이 아니다


def test_unrelated_number_does_not_trigger_retry():
    """본문에 우연히 숫자가 있다고 재시도하면 안 된다 — 5xx 코드만 신호로 본다."""
    assert not _is_retryable(400, '{"message":"row 502031 is invalid"}')
