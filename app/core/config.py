"""Application settings, read once from environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = "Compass"
    business_name: str = "Brightloom (fictional)"
    groq_api_key: str = ""
    groq_model: str = ""
    groq_timeout: float = 30.0
    state_file: Path = BASE_DIR / "instance" / "demo_state.json"

    @property
    def groq_configured(self) -> bool:
        placeholder = {"", "your_groq_api_key_here"}
        return self.groq_api_key.strip() not in placeholder


@lru_cache
def get_settings() -> Settings:
    model = os.getenv("GROQ_MODEL", "").strip()
    if model == "your_current_supported_model":
        model = ""
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=model,
        groq_timeout=float(os.getenv("GROQ_TIMEOUT_SECONDS", "30")),
    )
