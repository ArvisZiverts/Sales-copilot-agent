from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Apify
    apify_token: str = ""
    apify_linkedin_actor: str = "harvestapi~linkedin-profile-scraper"
    apify_website_actor: str = "apify~website-content-crawler"
    apify_timeout_seconds: int = 300
    website_max_pages: int = 8
    # The headless-browser retry is far slower per page, so it crawls fewer of them.
    # Homepage + a couple of nav pages is enough to qualify a lead.
    website_fallback_max_pages: int = 4

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    # gpt-5-mini reasoning depth: minimal | low | medium | high
    openai_reasoning_effort: str = "medium"

    # Typeform
    typeform_webhook_secret: str = ""
    allow_unsigned_webhooks: bool = False

    # Google Sheets
    google_service_account_b64: str = ""
    google_sheet_id: str = ""
    google_sheet_tab: str = "Leads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
