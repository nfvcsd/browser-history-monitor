from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    dev_extension_token: str
    dev_admin_token: str = ""
    auth_mode: Literal["development", "google"] = "google"
    google_client_id: str = ""
    google_workspace_domains: str = ""
    admin_emails: str = ""
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def workspace_domain_set(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.google_workspace_domains.split(",")
            if value.strip()
        }

    @property
    def admin_email_set(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.admin_emails.split(",")
            if value.strip()
        }

    @property
    def google_auth_ready(self) -> bool:
        return bool(
            self.google_client_id.strip()
            and self.workspace_domain_set
            and self.admin_email_set
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
