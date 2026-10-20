"""임베딩 설정을 .env 에서 시스템 DB·관리 화면으로 옮긴 것(2026-10-20)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import pgxnl.api.routes_admin as ra
from pgxnl.llm.embedding_config import EMBEDDING_DIMENSIONS, EmbeddingConfig, legacy_env_config


def _settings(**kw):
    base = {"embedding_provider": "openai_compatible", "embedding_model": "granite-embedding-278m",
            "embedding_base_url": "http://192.168.0.100:8001/v1", "embedding_api_key": "local"}
    base.update(kw)
    return SimpleNamespace(**base)


def test_legacy_env_migrates_openai_compatible():
    cfg, key = legacy_env_config(_settings())
    assert (cfg.provider, cfg.model, cfg.base_url, key) == (
        "openai_compatible", "granite-embedding-278m", "http://192.168.0.100:8001/v1", "local")


@pytest.mark.parametrize("kw", [{"embedding_api_key": ""}, {"embedding_api_key": "dummy"},
                                {"embedding_provider": "watsonx"}])
def test_legacy_env_skips_disabled_or_watsonx(kw):
    # 예전 규칙에서 빈 키·dummy 는 "임베딩 안 씀" 이었다. watsonx 는 등록 모델과 연결할 수 없어 옮기지 않는다
    assert legacy_env_config(_settings(**kw)) is None


def test_same_model_ignores_connection_options():
    a = EmbeddingConfig("openai_compatible", "m", "http://h:8001/v1", verify_ssl=True, has_api_key=True)
    assert a.same_model(EmbeddingConfig("openai_compatible", "m", "http://h:8001/v1/", verify_ssl=False))
    assert not a.same_model(EmbeddingConfig("openai_compatible", "m2", "http://h:8001/v1"))
    assert not a.same_model(None)  # 처음 설정 → 벡터를 만들어야 한다


def test_body_validation():
    with pytest.raises(HTTPException):
        ra._embedding_from_body(ra.EmbeddingBody(provider="openai_compatible", model="m"))  # base_url 없음
    with pytest.raises(HTTPException):
        ra._embedding_from_body(ra.EmbeddingBody(provider="watsonx", model="m"))  # 연결 모델 없음
    with pytest.raises(HTTPException):
        ra._embedding_from_body(ra.EmbeddingBody(provider="ollama", model="m", base_url="http://x"))
    cfg = ra._embedding_from_body(ra.EmbeddingBody(provider="watsonx", model="m", base_url="http://x", profile_id=3))
    assert cfg.base_url is None and cfg.profile_id == 3


async def _probe_with(monkeypatch, dims=None, exc=None):
    from pgxnl.api.state import state

    async def fake_build(cfg, api_key=None):
        async def embed(text):
            if exc:
                raise exc
            return [0.0] * dims
        return embed

    monkeypatch.setattr(state, "build_embed_fn", fake_build)
    return await ra._probe_embedding(EmbeddingConfig("openai_compatible", "m", "http://x"), None)


async def test_probe_ok(monkeypatch):
    r = await _probe_with(monkeypatch, dims=EMBEDDING_DIMENSIONS)
    assert r["ok"] and r["dimensions"] == EMBEDDING_DIMENSIONS


async def test_probe_rejects_wrong_dimension(monkeypatch):
    r = await _probe_with(monkeypatch, dims=1536)
    assert not r["ok"] and r["dimensions"] == 1536 and "768" in r["error"]


async def test_probe_reports_connection_error(monkeypatch):
    r = await _probe_with(monkeypatch, exc=ConnectionError("refused"))
    assert not r["ok"] and "refused" in r["error"]
