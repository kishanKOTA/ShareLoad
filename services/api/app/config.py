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
    demo_mode: bool
    environment: str
    use_gemini: bool
    runtime_dir: Path


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
    def boolean(name: str, default: str) -> bool:
        value = os.getenv(name, default).lower().strip()
        if value not in {"true", "false"}:
            raise ValueError(f"{name} must be true or false")
        return value == "true"
    environment = os.getenv("SHARELOAD_ENV", "development").strip().lower()
    if environment not in {"development", "test", "demo", "production"}:
        raise ValueError("SHARELOAD_ENV must be development, test, demo or production")
    demo_mode = boolean("SHARELOAD_DEMO_MODE", "false")
    if environment == "production" and demo_mode:
        raise ValueError("SHARELOAD_DEMO_MODE cannot be enabled in production")
    database_path = path_setting("SHARELOAD_DATABASE_PATH", "services/api/shareload.db")
    return Settings(
        data_dir=path_setting("SHARELOAD_DATA_DIR", "data/demo"),
        database_path=database_path,
        cors_origins=origins,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or "gemini-flash-latest",
        gemini_timeout_ms=timeout,
        demo_mode=demo_mode,
        environment=environment,
        use_gemini=boolean("SHARELOAD_USE_GEMINI", "true"),
        runtime_dir=path_setting("SHARELOAD_RUNTIME_DIR", str(database_path.parent / "runtime")),
    )
