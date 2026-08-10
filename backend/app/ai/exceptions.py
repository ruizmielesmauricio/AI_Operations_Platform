class AIProviderError(Exception):
    """A call to the AI provider (OpenRouter) failed — network error,
    timeout, or a non-2xx response. Kept independent of `httpx`'s own
    exception types so callers outside app/ai/client.py never need to
    import httpx to handle this case. Callers (app/ai/service.py) are
    expected to catch this and degrade gracefully (PR-5.4) — never let
    it surface as an unhandled 500.
    """
