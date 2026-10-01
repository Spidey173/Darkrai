from fastapi import APIRouter
from backend.app.api.v1.endpoints import health, auth, repos, webhooks, dashboard, rules

api_router = APIRouter()

# Register endpoint routers
api_router.include_router(health.router, prefix="", tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(repos.router, prefix="/repos", tags=["repos"])
api_router.include_router(rules.router, prefix="", tags=["rules"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
