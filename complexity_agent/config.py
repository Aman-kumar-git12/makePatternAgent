"""Settings from environment variables (and an optional .env file next to app.py)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _origins() -> list[str]:
    raw = os.getenv("AGENT_CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip()]


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("AGENT_HOST", "127.0.0.1")
    port: int = int(os.getenv("AGENT_PORT", "8001"))
    # Extra allowed browser origins (comma-separated). Extensions and localhost are always allowed.
    cors_origins: tuple[str, ...] = tuple(_origins())
    # Requests per minute per client IP.
    rate_limit: int = int(os.getenv("AGENT_RATE_LIMIT", "30"))
    reload: bool = os.getenv("AGENT_RELOAD", "false").lower() == "true"


settings = Settings()
