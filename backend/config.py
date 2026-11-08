from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file without overriding real env vars."""
    env_path = path or Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    value = os.environ.get(key, default)
    return value.strip()


AI_PROVIDER = _env("AI_PROVIDER", "none")
AI_API_KEY = _env("AI_API_KEY", "")
AI_BASE_URL = _env("AI_BASE_URL", "https://api.openai.com/v1")
AI_MODEL = _env("AI_MODEL", "gpt-4o-mini")
DATA_DIR = Path(_env("DATA_DIR", "data")).resolve()

MAX_UPLOAD_SIZE_MB = 200
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
ALLOWED_MIME_PREFIXES = ("application/pdf",)

AI_PROVIDERS = {"none", "openai-compatible", "anthropic-compatible"}


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ("uploads", "exports", "generated", "extracted"):
        (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
    return DATA_DIR
