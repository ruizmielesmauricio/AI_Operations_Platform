from fastapi import APIRouter

from app.api import alerts, analytics, billing, businesses, health, imports, uploads

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(businesses.router)
api_router.include_router(billing.router)
api_router.include_router(billing.webhook_router)
api_router.include_router(uploads.router)
api_router.include_router(imports.router)
api_router.include_router(analytics.router)
api_router.include_router(alerts.router)
