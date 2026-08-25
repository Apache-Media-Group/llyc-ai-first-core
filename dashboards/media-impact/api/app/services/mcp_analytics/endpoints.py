# backend/app/services/mcp_analytics/endpoints.py
from fastapi import APIRouter

from app.services.mcp_analytics.routes.tenant import router as tenant_router
from app.services.mcp_analytics.routes.oauth import router as oauth_router
from app.services.mcp_analytics.routes.analytics import router as analytics_router
from app.services.mcp_analytics.routes.chat_ai import router as chat_ai_router
from app.services.mcp_analytics.routes.admin_etl import router as admin_etl_router
from app.services.mcp_analytics.routes.connections import router as connections_router

router = APIRouter()

router.include_router(tenant_router)
router.include_router(oauth_router)
router.include_router(analytics_router)
router.include_router(chat_ai_router)
router.include_router(admin_etl_router)
router.include_router(connections_router)
