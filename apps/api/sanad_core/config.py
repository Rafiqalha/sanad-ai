from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = None
    openai_model: str | None = None
    brave_search_api_key: str | None = None
    hadith_api_key: str | None = None
    sunnah_api_key: str | None = None
    openalex_api_key: str | None = None
    wikipedia_langs: str = "id,en"
    crossref_mailto: str | None = None
    crossref_user_agent: str = "SANAD.AI/0.2"
    quran_foundation_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "QURAN_FOUNDATION_CLIENT_ID",
            "QF_CLIENT_ID",
        ),
    )
    quran_foundation_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "QURAN_FOUNDATION_CLIENT_SECRET",
            "QF_CLIENT_SECRET",
        ),
    )
    quran_foundation_env: Literal["prelive", "production"] = Field(
        default="prelive",
        validation_alias=AliasChoices(
            "QURAN_FOUNDATION_ENV",
            "QF_ENV",
        ),
    )

    sanad_http_timeout: float = 12.0
    sanad_max_web_results: int = 10
    sanad_hadith_api_page_size: int = Field(default=25, ge=1, le=200)
    sanad_quran_max_results: int = Field(default=5, ge=1, le=20)
    sanad_scholarly_max_results: int = Field(default=5, ge=1, le=20)
    sanad_max_brave_requests: int = Field(default=2, ge=1, le=3)
    sanad_max_web_pages: int = Field(default=3, ge=1, le=5)
    sanad_web_cache_ttl_seconds: int = Field(default=900, ge=60, le=86400)
    sanad_knowledge_cache_ttl_seconds: int = Field(
        default=3600,
        ge=60,
        le=86400,
    )
    sanad_web_max_content_bytes: int = Field(
        default=750_000,
        ge=50_000,
        le=2_000_000,
    )
    sanad_enable_broad_web_discovery: bool = True
    sanad_enable_history_academic_retrieval: bool = True
    # Remote semantic generation is opt-in. The current upgrade deliberately
    # runs locally and never calls OpenAI, even if legacy credentials exist.
    sanad_enable_remote_semantic: bool = False
    sanad_enable_semantic_rerank: bool = False
    sanad_semantic_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
