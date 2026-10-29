"""Authentication for non-public API routes."""

import hashlib
import logging
import secrets
from typing import Annotated, NoReturn

from fastapi import HTTPException, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.responses import Response

from app.config import get_settings

logger = logging.getLogger(__name__)

API_KEY_HEADER = "X-API-Key"
api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description="API key required for non-public routes.",
)


def api_keys_match(provided: str, expected: str) -> bool:
    """Compare API keys without a short-circuit on the first differing character."""
    provided_digest = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return secrets.compare_digest(provided_digest, expected_digest)


def require_api_key(
    provided_key: Annotated[str | None, Security(api_key_header)],
) -> str:
    """Reject missing and incorrect keys with the same response."""
    if provided_key is None or not _is_valid_api_key(provided_key):
        _reject_api_key()
    return provided_key


def _is_valid_api_key(provided_key: str | None) -> bool:
    if not provided_key:
        return False
    expected = get_settings().api_key.get_secret_value()
    return api_keys_match(provided_key, expected)


def _reject_api_key() -> NoReturn:
    logger.warning("Rejected request with an invalid or missing API key")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
        headers={"WWW-Authenticate": "APIKey"},
    )


async def reject_unauthorized_api_calls(request: Request, call_next) -> Response:
    """Require a valid API key for every path under /api."""
    path = request.url.path
    if path == "/api" or path.startswith("/api/"):
        if not _is_valid_api_key(request.headers.get(API_KEY_HEADER)):
            logger.warning("Rejected request with an invalid or missing API key")
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "APIKey"},
            )
    return await call_next(request)
