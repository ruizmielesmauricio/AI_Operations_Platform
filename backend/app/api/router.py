from fastapi import APIRouter

from app.api import (
    ai,
    alerts,
    analytics,
    audit_logs,
    billing,
    businesses,
    employee_seats,
    health,
    imports,
    notifications,
    product_categories,
    products,
    reports,
    search,
    suppliers,
    transactions,
    uploads,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(businesses.router)
api_router.include_router(audit_logs.router)
api_router.include_router(employee_seats.router)
api_router.include_router(billing.router)
api_router.include_router(billing.webhook_router)
api_router.include_router(uploads.router)
api_router.include_router(imports.router)
api_router.include_router(analytics.router)
api_router.include_router(alerts.router)
api_router.include_router(notifications.router)
api_router.include_router(reports.router)
api_router.include_router(ai.router)
api_router.include_router(product_categories.router)
api_router.include_router(products.router)
api_router.include_router(suppliers.router)
api_router.include_router(transactions.router)
api_router.include_router(search.router)
