import httpx
import openai
import pytest

from pgxnl.llm.openai_compatible import OpenAICompatibleClient

_REQ = httpx.Request("POST", "http://x/v1/chat/completions")


class _Fake:
    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def _client(fake, monkeypatch):
    c = OpenAICompatibleClient(model="m", base_url="http://x/v1", api_key="k")
    monkeypatch.setattr(c._client.chat, "completions", fake)
    monkeypatch.setattr("pgxnl.llm.openai_compatible.asyncio.sleep", _nosleep)
    return c


async def _nosleep(_):
    return None


def test_sdk_retries_disabled():
    c = OpenAICompatibleClient(model="m", base_url="http://x/v1", api_key="k")
    assert c._client.max_retries == 0


@pytest.mark.asyncio
async def test_timeout_is_not_retried(monkeypatch):
    fake = _Fake([openai.APITimeoutError(request=_REQ)])
    with pytest.raises(openai.APITimeoutError):
        await _client(fake, monkeypatch)._create_with_retry()
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_connection_error_is_retried(monkeypatch):
    fake = _Fake([openai.APIConnectionError(request=_REQ), openai.APIConnectionError(request=_REQ)])
    assert await _client(fake, monkeypatch)._create_with_retry() == "ok"
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_connection_error_gives_up_after_budget(monkeypatch):
    fake = _Fake([openai.APIConnectionError(request=_REQ)] * 3)
    with pytest.raises(openai.APIConnectionError):
        await _client(fake, monkeypatch)._create_with_retry()
    assert fake.calls == 3
