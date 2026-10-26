from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_publishable_key: str = ""
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0, le=20 * 1024 * 1024)
    max_pdf_pages: int = Field(default=200, gt=0, le=200)
    max_extracted_characters: int = Field(default=2_000_000, gt=0, le=2_000_000)
    pdf_timeout_seconds: float = Field(default=20, gt=0, le=60)
    cors_origins: list[str] = ["http://localhost:3000"]
