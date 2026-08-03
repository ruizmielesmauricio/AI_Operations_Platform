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
    # A non-empty placeholder so local/test JWT signing works out of the box
    # (PyJWT rejects an empty HMAC key). Production must override this via
    # env var with the real secret from the Supabase project dashboard —
    # never commit a real secret here.
    supabase_jwt_secret: str = "local-dev-secret-change-me-before-any-real-deployment"

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""

    openrouter_api_key: str = ""

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
