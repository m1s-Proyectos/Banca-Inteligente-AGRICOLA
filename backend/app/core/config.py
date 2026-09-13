from functools import cached_property

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://app:password@localhost:5432/collections"
    retell_api_key: str = ""
    retell_agent_id: str = ""
    retell_from_number: str = ""
    public_base_url: str = "http://localhost:8000"
    app_secret: str = "change-me"
    fake_data_only: bool = True
    retell_allowed_test_numbers: str = Field(default="")

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "https://banca-inteligente-one.vercel.app"]

    @cached_property
    def allowed_numbers(self) -> set[str]:
        return {item.strip() for item in self.retell_allowed_test_numbers.split(",") if item.strip()}


settings = Settings()

