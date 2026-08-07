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
    # behaviour"). Both also verified compliant with data_collection=deny
    # — currently prone to free-tier shared-pool rate-limiting (expected
    # for a free model, not a bug), which is exactly what a fallback
    # chain is for.
    openrouter_fallback_models: str = "google/gemma-4-31b-it:free,inclusionai/ling-3.0-tiny:free"
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

    resend_api_key: str = ""

    app_base_url: str = "http://localhost:3000"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
