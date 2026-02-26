from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    user_agent_email: str = os.getenv("USER_AGENT_EMAIL", "you@example.com")

    ithenticate_enabled: bool = os.getenv("ITHENTICATE_ENABLED", "false").lower() in ("1", "true", "yes")
    ithenticate_api_key: str | None = os.getenv("ITHENTICATE_API_KEY")
    ithenticate_base_url: str | None = os.getenv("ITHENTICATE_BASE_URL")


settings = Settings()
