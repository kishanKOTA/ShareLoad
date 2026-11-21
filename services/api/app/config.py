"""Platform settings. Process environment takes precedence over repo-root .env."""
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    cors_origins: tuple[str, ...]
    gemini_api_key: str | None
    gemini_model: str
    gemini_timeout_ms: int


def get_config() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    origins = tuple(o.strip() for o in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",") if o.strip())
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.path or parsed.query or parsed.fragment or parsed.username
                or parsed.password or "*" in origin):
            raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins without paths")
    timeout = int(os.getenv("GEMINI_TIMEOUT_MS", "30000"))
    if timeout <= 0:
        raise ValueError("GEMINI_TIMEOUT_MS must be positive")
    def path_setting(name: str, default: str) -> Path:
        path = Path(os.getenv(name, default)).expanduser()
        return path if path.is_absolute() else ROOT / path
    return Settings(
        data_dir=path_setting("SHARELOAD_DATA_DIR", "data/demo"),
        database_path=path_setting("SHARELOAD_DATABASE_PATH", "services/api/shareload.db"),
        cors_origins=origins,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or "gemini-flash-latest",
        gemini_timeout_ms=timeout,
    )
