"""Direct boundary to the OpenRouter HTTP API (an OpenAI-compatible
chat-completions endpoint) — no other module makes an AI-provider HTTP
call (CLAUDE.md: no provider SDK outside backend/app/ai/). One level
below app/ai/service.py, mirroring the app/billing/client.py <->
service.py and app/imports/r2_client.py <-> service.py splits already
used in this codebase.
"""

import httpx

from app.ai.exceptions import AIProviderError
from app.settings.config import get_settings


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

    try:
        response = httpx.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers=_headers(),
            json=body,
            timeout=settings.ai_request_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # The response body carries OpenRouter's actual error detail
        # (bad model id, no credits, auth failure, ...) — str(exc) alone
        # is just the status line, not enough to debug a live failure.
        raise AIProviderError(f"{exc}: {exc.response.text}") from exc
    except httpx.HTTPError as exc:
        raise AIProviderError(str(exc)) from exc

    return response.json()
