"""
模型管理相关 Admin API
"""

from fastapi import APIRouter

from .catalog import router as catalog_router
from .global_models import router as global_models_router

router = APIRouter(prefix="/api/admin/models", tags=["Admin - Model Management"])

# 挂载子路由
router.include_router(catalog_router)
router.include_router(global_models_router)
