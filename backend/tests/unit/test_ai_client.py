"""Covers app/ai/client.py's own retry-on-429 logic, mocking httpx.post
directly (no `respx` dependency in this codebase) — same "mock the vendor
call itself" style used for app.ai.client.chat_completion in the
integration chat tests, one level lower.
"""

import httpx
import pytest

from app.ai import client
from app.ai.exceptions import AIProviderError


def _response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return httpx.Response(status_code, json=json_body or {}, request=request)


def test_chat_completion_returns_the_parsed_response_on_success(monkeypatch):
    def _fake_post(*args, **kwargs):
        return _response(200, {"choices": [{"message": {"content": "hi"}}]})

    monkeypatch.setattr(httpx, "post", _fake_post)

    result = client.chat_completion(messages=[{"role": "user", "content": "test"}])

    assert result["choices"][0]["message"]["content"] == "hi"


def test_chat_completion_retries_once_after_a_429_and_succeeds(monkeypatch):
    calls = []
    sleeps = []

    def _fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return _response(429, {"error": {"message": "rate limited"}})
        return _response(200, {"choices": [{"message": {"content": "recovered"}}]})

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(client.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = client.chat_completion(messages=[{"role": "user", "content": "test"}])

    assert result["choices"][0]["message"]["content"] == "recovered"
    assert len(calls) == 2  # the original attempt, plus exactly one retry
    assert sleeps == [client._RATE_LIMIT_RETRY_BACKOFF_SECONDS]


def test_chat_completion_raises_after_429_on_every_attempt(monkeypatch):
    calls = []

    def _fake_post(*args, **kwargs):
        calls.append(1)
        return _response(429, {"error": {"message": "rate limited"}})

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(client.time, "sleep", lambda seconds: None)

    with pytest.raises(AIProviderError):
        client.chat_completion(messages=[{"role": "user", "content": "test"}])

    # Original attempt + _RATE_LIMIT_RETRY_ATTEMPTS retries, never more —
    # still degrades gracefully (PR-5.4), just after genuinely trying.
    assert len(calls) == client._RATE_LIMIT_RETRY_ATTEMPTS + 1


def test_chat_completion_does_not_retry_on_a_non_429_http_error(monkeypatch):
    # A bad model id / no credits / auth failure won't resolve itself on
    # a retry — retrying would only add latency for no benefit.
    calls = []
    sleeps = []

    def _fake_post(*args, **kwargs):
        calls.append(1)
        return _response(400, {"error": {"message": "invalid request"}})

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(client.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(AIProviderError):
        client.chat_completion(messages=[{"role": "user", "content": "test"}])

    assert len(calls) == 1
    assert sleeps == []


def test_chat_completion_does_not_retry_on_a_network_error(monkeypatch):
    # A connection-level failure isn't provider-side congestion — no
    # reason to expect a retry on the same short schedule to behave
    # differently, so fail immediately rather than doubling the wait.
    calls = []
    sleeps = []

    def _fake_post(*args, **kwargs):
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _fake_post)
    monkeypatch.setattr(client.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(AIProviderError):
        client.chat_completion(messages=[{"role": "user", "content": "test"}])

    assert len(calls) == 1
    assert sleeps == []


def test_chat_completion_includes_every_fallback_model_in_the_request_body(monkeypatch):
    # Confirms the diversified fallback chain (three providers, per
    # app/settings/config.py's own comment) actually reaches the request.
    captured_bodies = []

    def _fake_post(*args, **kwargs):
        captured_bodies.append(kwargs["json"])
        return _response(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx, "post", _fake_post)

    client.chat_completion(messages=[{"role": "user", "content": "test"}])

    models = captured_bodies[0]["models"]
    assert len(models) == 3
    assert len({m.split("/")[0] for m in models}) == 3  # 3 distinct providers


def test_chat_completion_never_sends_more_models_than_openrouter_allows(monkeypatch):
    # Real bug, live-verified: OpenRouter's own API rejects a `models`
    # array longer than 3 with a 400. Defends against a future
    # app/settings/config.py edit silently reintroducing a 4th fallback.
    captured_bodies = []

    def _fake_post(*args, **kwargs):
        captured_bodies.append(kwargs["json"])
        return _response(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(httpx, "post", _fake_post)
    oversized_settings = client.get_settings().model_copy(
        update={"openrouter_fallback_models": "a/one:free,b/two:free,c/three:free,d/four:free"}
    )
    monkeypatch.setattr(client, "get_settings", lambda: oversized_settings)

    client.chat_completion(messages=[{"role": "user", "content": "test"}])

    assert len(captured_bodies[0]["models"]) == client._MAX_MODELS_PER_REQUEST
