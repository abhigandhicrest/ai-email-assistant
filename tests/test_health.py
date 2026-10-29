"""Health endpoint tests. Ollama is mocked; no live service is required."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import PLACEHOLDER_API_KEY, get_settings


def test_health_is_public(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ignores_api_key(client: TestClient) -> None:
    response = client.get("/health", headers={"X-API-Key": "not-the-real-key!!"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ollama_health_when_service_responds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.ollama_service.httpx.AsyncClient",
        _client_returning(200, '{"version":"0.0.0","secret":"should-not-leak"}'),
    )

    response = client.get("/health/ollama")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "ollama": "reachable"}
    assert "should-not-leak" not in response.text


def test_ollama_health_when_service_returns_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.ollama_service.httpx.AsyncClient",
        _client_returning(500, "model path D:\\private\\weights"),
    )

    response = client.get("/health/ollama")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "ollama": "unreachable"}
    assert "private" not in response.text


def test_ollama_health_when_service_is_down(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://secret-ollama-host.example")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.ollama_service.httpx.AsyncClient",
        _client_raising(httpx.ConnectError("connection refused")),
    )

    response = client.get("/health/ollama")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "ollama": "unreachable"}
    assert "secret-ollama-host" not in response.text


def test_example_env_placeholder_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    placeholder = _example_value("API_KEY")
    assert placeholder == PLACEHOLDER_API_KEY
    monkeypatch.setenv("API_KEY", placeholder)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="Invalid configuration"):
        get_settings()


def test_short_api_key_is_rejected_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("API_KEY", "tiny-secret")
    get_settings.cache_clear()

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError, match="Invalid configuration") as raised:
            get_settings()

    assert "tiny-secret" not in str(raised.value)
    assert "tiny-secret" not in caplog.text


def test_ollama_url_with_credentials_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(
        "OLLAMA_BASE_URL",
        "http://user:secretpass@127.0.0.1:11434",
    )
    get_settings.cache_clear()

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError, match="Invalid configuration"):
            get_settings()

    assert "secretpass" not in caplog.text


def test_unhandled_error_hides_exception_text() -> None:
    from app.main import create_app

    application = create_app()

    @application.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("database password=super-secret-db")

    with TestClient(application, raise_server_exceptions=False) as test_client:
        response = test_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "super-secret-db" not in response.text


def _example_value(name: str) -> str:
    example = Path(".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"{name} is missing from .env.example")


def _client_returning(status_code: int, body: str):
    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            del args
            return False

        async def get(self, url: str) -> httpx.Response:
            assert url.endswith("/api/version")
            return httpx.Response(status_code, text=body)

    return FakeClient


def _client_raising(exc: Exception):
    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            del args
            return False

        async def get(self, url: str) -> httpx.Response:
            del url
            raise exc

    return FakeClient


def test_settings_round_trip_uses_test_key(api_key: str) -> None:
    assert get_settings().api_key.get_secret_value() == api_key
