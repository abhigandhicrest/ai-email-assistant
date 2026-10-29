"""Public health checks for the API process and Ollama."""

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from app.services.ollama_service import OllamaService

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: Literal["ok"]


class OllamaHealthStatus(BaseModel):
    status: Literal["ok", "unavailable"]
    ollama: Literal["reachable", "unreachable"]


@router.get("/health")
def health() -> HealthStatus:
    """Report that the API process is running."""
    return HealthStatus(status="ok")


@router.get(
    "/health/ollama",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": OllamaHealthStatus},
    },
)
async def ollama_health(response: Response) -> OllamaHealthStatus:
    """Report whether the configured Ollama server accepts connections."""
    reachable = await OllamaService().check_reachable()
    if not reachable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return OllamaHealthStatus(status="unavailable", ollama="unreachable")
    return OllamaHealthStatus(status="ok", ollama="reachable")
