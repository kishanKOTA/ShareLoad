import pytest

from app.agent import config as agent_config


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    # Point at an empty .env so a developer's real key never leaks into tests.
    monkeypatch.setattr(agent_config, "ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    agent_config.reset_config_cache()
    yield
    agent_config.reset_config_cache()


def test_missing_key_falls_back_to_template():
    config = agent_config.get_config()
    assert config.gemini_api_key is None
    assert config.mode == "template"
    assert agent_config.get_gemini_client() is None


def test_blank_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert agent_config.get_config().mode == "template"
    assert agent_config.get_gemini_client() is None


def test_key_read_from_dotenv_file(tmp_path):
    (tmp_path / ".env").write_text("GEMINI_API_KEY=test-key\n", encoding="utf-8")
    config = agent_config.get_config()
    assert config.gemini_api_key == "test-key"
    assert config.mode == "gemini"


def test_client_init_failure_degrades_to_template(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from google import genai

    def boom(**_):
        raise RuntimeError("init failed")

    monkeypatch.setattr(genai, "Client", boom)
    assert agent_config.get_gemini_client() is None


def test_model_defaults_to_fast_flash():
    assert agent_config.get_config().gemini_model == agent_config.DEFAULT_GEMINI_MODEL


def test_model_read_from_dotenv_file(tmp_path):
    (tmp_path / ".env").write_text("GEMINI_MODEL=gemini-2.5-flash\n", encoding="utf-8")
    assert agent_config.get_config().gemini_model == "gemini-2.5-flash"
