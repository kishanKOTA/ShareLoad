"""Server-side Gemini boundary; deliberately independent of the matching agent."""
from app.config import get_config


def get_gemini_client():
    config = get_config()
    if not config.gemini_api_key:
        return None
    from google import genai
    from google.genai import types
    return genai.Client(
        api_key=config.gemini_api_key,
        http_options=types.HttpOptions(
            timeout=config.gemini_timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
