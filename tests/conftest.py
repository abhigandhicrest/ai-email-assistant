"""Shared test configuration.

Environment values are set before the application is imported so tests never
fall back to a developer `.env` file.
"""

import os

import pytest

TEST_API_KEY = "test-api-key-value"

os.environ["API_KEY"] = TEST_API_KEY
os.environ["APP_ENV"] = "test"
os.environ["APP_HOST"] = "127.0.0.1"
os.environ["APP_PORT"] = "8000"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434"
os.environ["OLLAMA_MODEL"] = "llama3.2"
os.environ["DATABASE_URL"] = (
    "mysql+pymysql://user:password@127.0.0.1:3306/ai_email_assistant"
)


@pytest.fixture(autouse=True)
def reset_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", TEST_API_KEY)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", "8000")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2")
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def api_key() -> str:
    return TEST_API_KEY


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
