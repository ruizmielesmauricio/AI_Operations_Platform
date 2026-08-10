"""Direct boundary to the OpenRouter HTTP API (an OpenAI-compatible
chat-completions endpoint) — no other module makes an AI-provider HTTP
call (CLAUDE.md: no provider SDK outside backend/app/ai/). One level
below app/ai/service.py, mirroring the app/billing/client.py <->
service.py and app/imports/r2_client.py <-> service.py splits already
used in this codebase.
"""

import time

import httpx

from app.ai.exceptions import AIProviderError
from app.settings.config import get_settings

# How many times to retry the WHOLE request (every model in the chain,
# not just one) after a 429 from every model in it. Live-verified during
# a fire test: under sustained load, OpenRouter's own per-request
# model-chain fallback (the `models` list below) can still exhaust every
# configured free model in a single attempt, but a short retry often
# succeeds — OpenRouter's routing isn't perfectly sticky, so a second
# attempt a couple of seconds later can land on a different, less-
# congested backend instance for the same free models. Bounded to one
# retry with a short fixed backoff (NOT the `retry_after_seconds` an
# OpenRouter 429 body reports, which can be 20+ seconds — too slow for a
# synchronous chat response the user is actively waiting on); if that
# also fails, this still degrades to the existing graceful
# "unavailable" fallback (PR-5.4), never a raised, unhandled error.
_RATE_LIMIT_RETRY_ATTEMPTS = 1
_RATE_LIMIT_RETRY_BACKOFF_SECONDS = 2.0
# OpenRouter's own hard limit on the `models` fallback array — live-
# verified via a real 400 ("'models' array must have 3 items or fewer")
# after this codebase briefly shipped a 4-model chain.
_MAX_MODELS_PER_REQUEST = 3


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # OpenRouter's own convention for attributing traffic — optional,
        # but recommended by their docs.
        "HTTP-Referer": settings.app_base_url,
        "X-Title": "AI Operations Platform",
    }


def chat_completion(
    *,
    messages: list[dict[str, str]],
    response_format: dict | None = None,
    max_tokens: int = 500,
    temperature: float = 0.2,
) -> dict:
    """One OpenRouter chat-completion call. Returns the raw parsed JSON
    response (caller extracts `choices[0].message.content` and `usage`)
    — kept intentionally thin; app/ai/service.py owns all business logic
    (which model, what happens to the answer, logging, validation).

    Raises AIProviderError on any network failure, timeout, or non-2xx
    response — the caller is responsible for catching this and degrading
    gracefully (PR-5.4), never surfacing it as an unhandled 500.
    """
    settings = get_settings()

    fallbacks = [m.strip() for m in settings.openrouter_fallback_models.split(",") if m.strip()]
    models = [settings.openrouter_model, *fallbacks]
    # OpenRouter's own API rejects a `models` array longer than 3 with a
    # 400 (live-verified) — capped here defensively, not just by keeping
    # app/settings/config.py's own list short, so a future edit that adds
    # one more fallback can't silently reintroduce every call failing.
    models = models[:_MAX_MODELS_PER_REQUEST]

    body: dict = {
        "model": settings.openrouter_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # OpenRouter's own mechanism for restricting routing to
        # providers that don't retain/train on request data — the
        # concrete, enforceable form of 05_AI_Architecture.md's "EU
        # regulatory fit" requirement, rather than a per-model judgment
        # call made in this codebase.
        "provider": {"data_collection": "deny"},
        # OpenRouter echoes the actual per-request cost back in the
        # response's usage.cost field when this is set — used for
        # AIRequest.cost_eur logging (app/ai/service.py) without this
        # codebase needing to maintain its own per-model price table.
        # Note: OpenRouter reports this in USD, not EUR — stored as-is,
        # a stated approximation rather than a real currency conversion.
        "usage": {"include": True},
    }
    if len(models) > 1:
        # OpenRouter tries these in order if the first fails/times out —
        # free fallback behaviour, no custom retry logic needed here.
        body["models"] = models
    if response_format is not None:
        body["response_format"] = response_format

    last_exc: Exception | None = None
    for attempt in range(_RATE_LIMIT_RETRY_ATTEMPTS + 1):
        if attempt > 0:
            time.sleep(_RATE_LIMIT_RETRY_BACKOFF_SECONDS)
        try:
            response = httpx.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers=_headers(),
                json=body,
                timeout=settings.ai_request_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code != 429 or attempt == _RATE_LIMIT_RETRY_ATTEMPTS:
                # Not a rate limit (a bad model id, no credits, auth
                # failure, ...) — retrying wouldn't help, fail now. The
                # response body carries OpenRouter's actual error detail;
                # str(exc) alone is just the status line, not enough to
                # debug a live failure.
                raise AIProviderError(f"{exc}: {exc.response.text}") from exc
            # 429 with a retry attempt left — every model in `models`
            # was rate-limited on this attempt, but OpenRouter's routing
            # isn't perfectly sticky, so a short pause and a fresh
            # attempt across the same model list can still land on a
            # backend that's since freed up.
        except httpx.HTTPError as exc:
            # A network-level failure (timeout, connection error) — not
            # provider-side congestion, so retrying on the same schedule
            # wouldn't be expected to behave differently; fail immediately
            # rather than doubling the user's wait for no real benefit.
            raise AIProviderError(str(exc)) from exc

    # Unreachable in practice (every loop iteration either returns or
    # raises), kept only so a type checker sees every path covered.
    raise AIProviderError(str(last_exc))
