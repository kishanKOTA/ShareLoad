"""Agent configuration: the Gemini API key, read from the repo-root ``.env``.

A missing or blank ``GEMINI_API_KEY`` is not an error. The agent then runs in
template mode: no Gemini calls, and the explanation comes from a fixed template
built only from tool outputs. ``get_gemini_client()`` returns ``None`` in that
case (and also if the client can't be created), so callers branch on it instead
of catching exceptions.

Variables already set in the process environment win over ``.env``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

log = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[4] / ".env"


@dataclass(frozen=True)
class AgentConfig:
    gemini_api_key: str | None

    @property
    def use_gemini(self) -> bool:
        return self.gemini_api_key is not None

    @property
    def mode(self) -> str:
        return "gemini" if self.use_gemini else "template"


@lru_cache(maxsize=1)
def get_config() -> AgentConfig:
    load_dotenv(ENV_PATH, override=False)
    key = (os.environ.get("GEMINI_API_KEY") or "").strip() or None
    if key is None:
        log.warning("GEMINI_API_KEY not set; agent will use template mode")
    return AgentConfig(gemini_api_key=key)


@lru_cache(maxsize=1)
def get_gemini_client() -> Any | None:
    """A ``google.genai.Client``, or None when running in template mode."""
    config = get_config()
    if not config.use_gemini:
        return None
    try:
        from google import genai

        return genai.Client(api_key=config.gemini_api_key)
    except Exception as exc:  # bad install or client init failure: degrade, don't crash
        log.warning("Gemini client unavailable (%s); agent will use template mode", exc)
        return None


def reset_config_cache() -> None:
    """Re-read the environment on next access (tests, or after editing .env)."""
    get_config.cache_clear()
    get_gemini_client.cache_clear()
