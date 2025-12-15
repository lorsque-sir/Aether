"""
缓存失效服务

统一管理各种缓存的失效逻辑，支持：
1. GlobalModel 变更时失效相关缓存
2. Model 变更时失效模型映射缓存
3. 支持同步和异步缓存后端
"""

from typing import Optional

from src.core.logger import logger


class CacheInvalidationService:
    """
    缓存失效服务

    提供统一的缓存失效接口，当数据库模型变更时自动清理相关缓存
    """

    def __init__(self):
        """初始化缓存失效服务"""
        self._model_mappers = []  # 可能有多个 ModelMapperMiddleware 实例

    def register_model_mapper(self, model_mapper):
        """注册 ModelMapper 实例"""
        if model_mapper not in self._model_mappers:
            self._model_mappers.append(model_mapper)
            logger.debug(f"[CacheInvalidation] ModelMapper 已注册 (实例: {id(model_mapper)}，总数: {len(self._model_mappers)})")

    def on_global_model_changed(self, model_name: str):
        """
        GlobalModel 变更时的缓存失效

        Args:
            model_name: 变更的 GlobalModel.name
        """
        logger.info(f"[CacheInvalidation] GlobalModel 变更: {model_name}")

        # 失效所有 ModelMapper 中与此模型相关的缓存
        for mapper in self._model_mappers:
            # 清空所有缓存（因为不知道哪些 provider 使用了这个模型）
            mapper.clear_cache()
            logger.debug(f"[CacheInvalidation] 已清空 ModelMapper 缓存")

    def on_model_changed(self, provider_id: str, global_model_id: str):
        """
        Model 变更时的缓存失效

        Args:
            provider_id: Provider ID
            global_model_id: GlobalModel ID
        """
        logger.info(f"[CacheInvalidation] Model 变更: provider={provider_id[:8]}..., "
            f"global_model={global_model_id[:8]}...")

        # 失效 ModelMapper 中特定 Provider 的缓存
        for mapper in self._model_mappers:
            mapper.refresh_cache(provider_id)

    def clear_all_caches(self):
        """清空所有缓存"""
        logger.info("[CacheInvalidation] 清空所有缓存")

        for mapper in self._model_mappers:
            mapper.clear_cache()


# 全局单例
_cache_invalidation_service: Optional[CacheInvalidationService] = None


def get_cache_invalidation_service() -> CacheInvalidationService:
    """
    获取全局缓存失效服务实例

    Returns:
        CacheInvalidationService 实例
    """
    global _cache_invalidation_service

    if _cache_invalidation_service is None:
        _cache_invalidation_service = CacheInvalidationService()
        logger.debug("[CacheInvalidation] 初始化缓存失效服务")

    return _cache_invalidation_service
