"""All settings come from environment variables (loaded from .env)."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # LLM
    llm_provider: str = os.getenv("LLM_PROVIDER", "groq").lower()
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # MongoDB
    mongo_uri: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    mongo_db: str = os.getenv("MONGO_DB", "code_review")

    # GitHub
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_webhook_secret: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    github_api_url: str = os.getenv("GITHUB_API_URL", "https://api.github.com")

    # App
    timezone: str = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    dev_endpoints: bool = _bool("DEV_ENDPOINTS", False)
    review_extensions: tuple = tuple(
        ext.strip() for ext in os.getenv("REVIEW_EXTENSIONS", ".py").split(",") if ext.strip()
    )

    # Reviewer agents
    reviewer_host: str = os.getenv("REVIEWER_HOST", "127.0.0.1")
    code_reviewer_url: str = os.getenv("CODE_REVIEWER_URL", "http://127.0.0.1:10001")
    best_practice_reviewer_url: str = os.getenv(
        "BEST_PRACTICE_REVIEWER_URL", "http://127.0.0.1:10002"
    )
    security_reviewer_url: str = os.getenv("SECURITY_REVIEWER_URL", "http://127.0.0.1:10003")
    reviewer_timeout_s: float = float(os.getenv("REVIEWER_TIMEOUT_SECONDS", "240"))

    # Limits
    max_files_per_push: int = int(os.getenv("MAX_FILES_PER_PUSH", "50"))
    max_file_bytes: int = int(os.getenv("MAX_FILE_BYTES", "200000"))
    llm_max_chars: int = int(os.getenv("LLM_MAX_CHARS", "24000"))


settings = Settings()
