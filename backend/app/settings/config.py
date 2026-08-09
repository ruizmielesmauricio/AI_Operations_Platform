from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central app configuration, loaded from environment variables.

    Every external vendor credential lives here and nowhere else, so swapping
    a vendor (per 04_Technology_Stack.md's portability principle) never means
    hunting through business logic for a hardcoded key.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    allowed_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+psycopg://aiops:aiops_dev_password@localhost:5432/aiops_dev"

    supabase_url: str = ""
    supabase_anon_key: str = ""

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # A single, plain config value rather than a dynamic cost/quality-
    # threshold selector (05_AI_Architecture.md's E21/E22 full vision) —
    # no evaluation test set exists yet to justify picking one
    # algorithmically. Swap this once a real model is chosen for launch.
    #
    # Live-verified against OpenRouter's real catalog (2026-08-06, with
    # provider.data_collection="deny" enforced, per app/ai/client.py):
    # almost every ":free" model requires accepting "free model training"
    # (i.e. the provider trains on your data) as the price of being free
    # — deny-data-collection eliminates most of them outright (404 "No
    # endpoints found matching your data policy"). This is a genuine
    # reasoning model (extra hidden "reasoning" tokens before the visible
    # answer — see the generous max_tokens below) so it costs more per
    # question than a plain instruct model; fine for testing, but prefer
    # a non-reasoning model (Haiku/GPT-4o-mini/Gemini Flash-class) for a
    # real launch, per the stated E21/E22 cost goal.
    openrouter_model: str = "openai/gpt-oss-20b:free"
    # Comma-separated OpenRouter model ids tried, in order, if the primary
    # model fails or times out (05_AI_Architecture.md's "fallback
    # behaviour"). Capped at 2 fallbacks (3 models total, including the
    # primary): OpenRouter's API itself rejects a `models` array longer
    # than 3 with a 400 — live-verified hitting this exact limit after
    # first trying 4 (also defended in code — see app/ai/client.py's
    # _MAX_MODELS_PER_REQUEST).
    #
    # Every candidate here was live-tested end-to-end against this app's
    # ACTUAL request shape (data_collection=deny + response_format=
    # json_object, both set on every call) before being added — a real
    # regression was caught doing this the first time: several
    # plausible-looking free models on OpenRouter's public catalog
    # (nvidia/nemotron-3-nano-30b-a3b:free, poolside/laguna-s-2.1:free)
    # 404 outright under data_collection=deny ("No endpoints found
    # matching your data policy (Free model training)" — i.e. that
    # provider's free tier requires allowing training on the data, which
    # this app's own privacy stance forbids), and the model that had been
    # sitting here since before this fix (inclusionai/ling-3.0-tiny:free)
    # 400s on every classify call specifically, because it doesn't
    # support structured-outputs mode at all — a pre-existing, silent gap
    # this investigation surfaced, not something introduced here.
    # cohere/north-mini-code:free is the replacement, confirmed live to
    # return clean, valid JSON under both restrictions. Re-verify before
    # relying on this list long-term — OpenRouter's free catalog, and
    # which providers permit data_collection=deny, both change over time.
    openrouter_fallback_models: str = "google/gemma-4-31b-it:free,cohere/north-mini-code:free"
    # PR-5.5 — per-tenant AI usage limit, enforced server-side. Raised
    # from 30 to 200 for the testing/pilot phase, per direct instruction:
    # the configured model is the `:free` OpenRouter tier (see
    # openrouter_model above), so every call costs this app literally
    # $0 regardless of this number — the OpenRouter account's own
    # daily quota on free models (up to 1000/day once funded with real
    # credit) is the only cost-relevant ceiling left, and 200 sits
    # comfortably under it. This value is NOT the mechanism for
    # controlling real per-client cost once launched on a paid model —
    # see the "Future Improvements" note in
    # docs/governance/11_Development_Roadmap.md for the intended
    # tiered-downgrade design (cap tied to a fraction of the €80/month
    # plan's token budget, falling back to a free model past a usage
    # threshold rather than hard-blocking further questions).
    ai_daily_request_limit_per_business: int = 200
    ai_request_timeout_seconds: int = 20

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""
    # A branch (Business.parent_business_id set) gets its own separate
    # Subscription row/Stripe subscription at this discounted price,
    # rather than a shared quantity line item on the primary shop's
    # subscription — reuses the exact same checkout/webhook/cancel flow
    # already built and tested for the primary price, just a different
    # price id (see app/billing/service.py::start_checkout).
    stripe_branch_price_id: str = ""
    # A paid employee seat (EUR 5/month, up to 2 per business) — its own
    # dedicated Stripe subscription, same shape as stripe_branch_price_id
    # above, just a distinct price point and metadata key
    # (employee_seat_id instead of no extra key at all — see
    # app/billing/service.py::_apply_event). Needs its own Price object
    # created in the Stripe Dashboard, same as the other two.
    stripe_employee_seat_price_id: str = ""

    resend_api_key: str = ""
    # The "from" address Resend sends as — Resend requires either a
    # verified sending domain or its own no-setup test address
    # (onboarding@resend.dev, real-mailbox-deliverable but rate-limited/
    # only for testing). Left blank by default rather than defaulting to
    # that test address, so a real deployment is never silently sending
    # from an address nobody configured on purpose.
    resend_from_email: str = ""

    # Address validation + geocoding for app/geocoding/client.py — empty by
    # default (never committed), matching every other optional provider key
    # in this file. "Validate address" degrades gracefully (a clear
    # "address validation isn't configured" result, never a crash) when
    # this is unset, same PR-5.4-style graceful-degradation posture already
    # used for the AI provider gateway.
    geoapify_api_key: str = ""

    app_base_url: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
