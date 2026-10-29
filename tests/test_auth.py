"""API key authentication. These tests do not call Ollama or MySQL."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import api_router
from app.api.dependencies import require_api_key


def test_api_router_declares_api_key_dependency() -> None:
    assert api_router.dependencies
    assert api_router.dependencies[0].dependency is require_api_key


def test_missing_api_key_is_rejected(client: TestClient, api_key: str) -> None:
    response = client.get("/api/emails")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    assert response.headers["www-authenticate"] == "APIKey"
    assert api_key not in response.text


def test_wrong_api_key_is_rejected(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrong_key = "wrong-api-key-value"

    with caplog.at_level("WARNING"):
        response = client.get("/api/emails", headers={"X-API-Key": wrong_key})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}
    assert wrong_key not in response.text
    assert wrong_key not in caplog.text


def test_valid_api_key_reaches_the_email_route(
    client: TestClient,
    api_key: str,
) -> None:
    response = client.post(
        "/api/emails/process",
        headers={"X-API-Key": api_key},
        json={},
    )

    assert response.status_code == 422
    assert api_key not in response.text


def test_empty_api_key_header_is_rejected(client: TestClient) -> None:
    response = client.get("/api/emails", headers={"X-API-Key": ""})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_http_exception_keeps_its_status(api_key: str) -> None:
    from fastapi import HTTPException

    from app.main import create_app

    application = create_app()

    @application.get("/api/probe", dependencies=[Depends(require_api_key)])
    def probe() -> dict[str, str]:
        raise HTTPException(status_code=400, detail="Bad request")

    with TestClient(application) as test_client:
        response = test_client.get("/api/probe", headers={"X-API-Key": api_key})

    assert response.status_code == 400
    assert response.json() == {"detail": "Bad request"}


def test_route_dependency_accepts_only_the_configured_key(api_key: str) -> None:
    application = FastAPI()

    @application.get("/secure", dependencies=[Depends(require_api_key)])
    def secure() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(application) as test_client:
        missing = test_client.get("/secure")
        wrong = test_client.get("/secure", headers={"X-API-Key": "wrong-api-key-value"})
        valid = test_client.get("/secure", headers={"X-API-Key": api_key})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert valid.status_code == 200
    assert valid.json() == {"status": "ok"}
    assert api_key not in valid.text
