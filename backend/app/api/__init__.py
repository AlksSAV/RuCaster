"""API маршруты."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.geo import router as geo_router
from app.api.monitoring import router as monitoring_router
from app.api.proxy import router as proxy_router
from app.api.records import router as records_router
from app.api.sources import router as sources_router

router = APIRouter()

router.include_router(auth_router, prefix="/api/auth", tags=["auth"])
router.include_router(sources_router, prefix="/api/sources", tags=["sources"])
router.include_router(monitoring_router, prefix="", tags=["monitoring"])
router.include_router(records_router, prefix="/api/record", tags=["records"])
router.include_router(proxy_router, prefix="/api/proxy", tags=["proxy"])
router.include_router(admin_router, prefix="/api/users", tags=["admin"])
router.include_router(geo_router, prefix="/api", tags=["geo"])
