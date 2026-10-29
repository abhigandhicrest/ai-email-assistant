"""HTTP routers."""

from fastapi import APIRouter, Depends

from app.api.dependencies import require_api_key
from app.api.email_routes import email_router

api_router = APIRouter(
    prefix="/api",
    tags=["api"],
    dependencies=[Depends(require_api_key)],
)
api_router.include_router(email_router)
