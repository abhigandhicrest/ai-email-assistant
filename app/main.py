"""FastAPI application entry point."""

import logging

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import api_router
from app.api.dependencies import reject_unauthorized_api_calls
from app.api.health_routes import router as health_router
from app.config import configure_logging, get_settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(
        title="AI Email Assistant",
        version="0.1.0",
        description=(
            "Local API for classifying email and storing suggested replies "
            "for human review."
        ),
    )
    application.middleware("http")(reject_unauthorized_api_calls)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.include_router(health_router)
    application.include_router(api_router)
    return application


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Return a fixed error body. The exception text stays in the log type only."""
    logger.error(
        "Unhandled error on %s %s (%s)",
        request.method,
        request.url.path,
        exc.__class__.__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
    )


if __name__ == "__main__":
    run()
