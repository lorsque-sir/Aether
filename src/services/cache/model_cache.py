"""
Model 映射缓存服务 - 减少模型查询
"""

from typing import Optional

from sqlalchemy.orm import Session

from src.config.constants import CacheTTL
from src.core.cache_service import CacheService
from src.core.logger import logger
from src.models.database import GlobalModel, Model


class ModelCacheService:
    """Model 映射缓存服务"""

    # 缓存 TTL（秒）- 使用统一常量
    CACHE_TTL = CacheTTL.MODEL

    @staticmethod
    async def get_model_by_id(db: Session, model_id: str) -> Optional[Model]:
        """
        获取 Model（带缓存）

        Args:
            db: 数据库会话
            model_id: Model ID

        Returns:
            Model 对象或 None
        """
        cache_key = f"model:id:{model_id}"

        # 1. 尝试从缓存获取
        cached_data = await CacheService.get(cache_key)
        if cached_data:
            logger.debug(f"Model 缓存命中: {model_id}")
            return ModelCacheService._dict_to_model(cached_data)

        # 2. 缓存未命中，查询数据库
        model = db.query(Model).filter(Model.id == model_id).first()

        # 3. 写入缓存
        if model:
            model_dict = ModelCacheService._model_to_dict(model)
            await CacheService.set(cache_key, model_dict, ttl_seconds=ModelCacheService.CACHE_TTL)
            logger.debug(f"Model 已缓存: {model_id}")

        return model

    @staticmethod
    async def get_global_model_by_id(db: Session, global_model_id: str) -> Optional[GlobalModel]:
        """
        获取 GlobalModel（带缓存）

        Args:
            db: 数据库会话
            global_model_id: GlobalModel ID

        Returns:
            GlobalModel 对象或 None
        """
        cache_key = f"global_model:id:{global_model_id}"

        # 1. 尝试从缓存获取
        cached_data = await CacheService.get(cache_key)
        if cached_data:
            logger.debug(f"GlobalModel 缓存命中: {global_model_id}")
            return ModelCacheService._dict_to_global_model(cached_data)

        # 2. 缓存未命中，查询数据库
        global_model = db.query(GlobalModel).filter(GlobalModel.id == global_model_id).first()

        # 3. 写入缓存
        if global_model:
            global_model_dict = ModelCacheService._global_model_to_dict(global_model)
            await CacheService.set(
                cache_key, global_model_dict, ttl_seconds=ModelCacheService.CACHE_TTL
            )
            logger.debug(f"GlobalModel 已缓存: {global_model_id}")

        return global_model

    @staticmethod
    async def get_model_by_provider_and_global_model(
        db: Session, provider_id: str, global_model_id: str
    ) -> Optional[Model]:
        """
        通过 Provider ID 和 GlobalModel ID 获取 Model（带缓存）

        Args:
            db: 数据库会话
            provider_id: Provider ID
            global_model_id: GlobalModel ID

        Returns:
            Model 对象或 None
        """
        cache_key = f"model:provider_global:{provider_id}:{global_model_id}"

        # 1. 尝试从缓存获取
        cached_data = await CacheService.get(cache_key)
        if cached_data:
            logger.debug(f"Model 缓存命中(provider+global): {provider_id[:8]}...+{global_model_id[:8]}...")
            return ModelCacheService._dict_to_model(cached_data)

        # 2. 缓存未命中，查询数据库
        model = (
            db.query(Model)
            .filter(
                Model.provider_id == provider_id,
                Model.global_model_id == global_model_id,
                Model.is_active == True,
            )
            .first()
        )

        # 3. 写入缓存
        if model:
            model_dict = ModelCacheService._model_to_dict(model)
            await CacheService.set(cache_key, model_dict, ttl_seconds=ModelCacheService.CACHE_TTL)
            logger.debug(f"Model 已缓存(provider+global): {provider_id[:8]}...+{global_model_id[:8]}...")

        return model

    @staticmethod
    async def get_global_model_by_name(db: Session, name: str) -> Optional[GlobalModel]:
        """
        通过名称获取 GlobalModel（带缓存）

        Args:
            db: 数据库会话
            name: GlobalModel 名称

        Returns:
            GlobalModel 对象或 None
        """
        cache_key = f"global_model:name:{name}"

        # 1. 尝试从缓存获取
        cached_data = await CacheService.get(cache_key)
        if cached_data:
            logger.debug(f"GlobalModel 缓存命中(名称): {name}")
            return ModelCacheService._dict_to_global_model(cached_data)

        # 2. 缓存未命中，查询数据库
        global_model = db.query(GlobalModel).filter(GlobalModel.name == name).first()

        # 3. 写入缓存
        if global_model:
            global_model_dict = ModelCacheService._global_model_to_dict(global_model)
            await CacheService.set(
                cache_key, global_model_dict, ttl_seconds=ModelCacheService.CACHE_TTL
            )
            logger.debug(f"GlobalModel 已缓存(名称): {name}")

        return global_model

    @staticmethod
    async def invalidate_model_cache(
        model_id: str, provider_id: Optional[str] = None, global_model_id: Optional[str] = None
    ):
        """清除 Model 缓存

        Args:
            model_id: Model ID
            provider_id: Provider ID（用于清除 provider_global 缓存）
            global_model_id: GlobalModel ID（用于清除 provider_global 缓存）
        """
        # 清除 model:id 缓存
        await CacheService.delete(f"model:id:{model_id}")

        # 清除 provider_global 缓存（如果提供了必要参数）
        if provider_id and global_model_id:
            await CacheService.delete(f"model:provider_global:{provider_id}:{global_model_id}")
            logger.debug(f"Model 缓存已清除: {model_id}, provider_global:{provider_id[:8]}...:{global_model_id[:8]}...")
        else:
            logger.debug(f"Model 缓存已清除: {model_id}")

    @staticmethod
    async def invalidate_global_model_cache(global_model_id: str, name: Optional[str] = None):
        """清除 GlobalModel 缓存"""
        await CacheService.delete(f"global_model:id:{global_model_id}")
        if name:
            await CacheService.delete(f"global_model:name:{name}")
        logger.debug(f"GlobalModel 缓存已清除: {global_model_id}")

    @staticmethod
    def _model_to_dict(model: Model) -> dict:
        """将 Model 对象转换为字典"""
        return {
            "id": model.id,
            "provider_id": model.provider_id,
            "global_model_id": model.global_model_id,
            "provider_model_name": model.provider_model_name,
            "provider_model_aliases": getattr(model, "provider_model_aliases", None),
            "is_active": model.is_active,
            "is_available": model.is_available if hasattr(model, "is_available") else True,
            "price_per_request": (
                float(model.price_per_request) if model.price_per_request else None
            ),
            "tiered_pricing": model.tiered_pricing,
            "supports_vision": model.supports_vision,
            "supports_function_calling": model.supports_function_calling,
            "supports_streaming": model.supports_streaming,
            "supports_extended_thinking": model.supports_extended_thinking,
            "supports_image_generation": getattr(model, "supports_image_generation", None),
            "config": model.config,
        }

    @staticmethod
    def _dict_to_model(model_dict: dict) -> Model:
        """从字典重建 Model 对象"""
        model = Model(
            id=model_dict["id"],
            provider_id=model_dict["provider_id"],
            global_model_id=model_dict["global_model_id"],
            provider_model_name=model_dict["provider_model_name"],
            provider_model_aliases=model_dict.get("provider_model_aliases"),
            is_active=model_dict["is_active"],
            is_available=model_dict.get("is_available", True),
            price_per_request=model_dict.get("price_per_request"),
            tiered_pricing=model_dict.get("tiered_pricing"),
            supports_vision=model_dict.get("supports_vision"),
            supports_function_calling=model_dict.get("supports_function_calling"),
            supports_streaming=model_dict.get("supports_streaming"),
            supports_extended_thinking=model_dict.get("supports_extended_thinking"),
            supports_image_generation=model_dict.get("supports_image_generation"),
            config=model_dict.get("config"),
        )
        return model

    @staticmethod
    def _global_model_to_dict(global_model: GlobalModel) -> dict:
        """将 GlobalModel 对象转换为字典"""
        return {
            "id": global_model.id,
            "name": global_model.name,
            "display_name": global_model.display_name,
            "default_supports_vision": global_model.default_supports_vision,
            "default_supports_function_calling": global_model.default_supports_function_calling,
            "default_supports_streaming": global_model.default_supports_streaming,
            "default_supports_extended_thinking": global_model.default_supports_extended_thinking,
            "default_supports_image_generation": global_model.default_supports_image_generation,
            "is_active": global_model.is_active,
            "description": global_model.description,
        }

    @staticmethod
    def _dict_to_global_model(global_model_dict: dict) -> GlobalModel:
        """从字典重建 GlobalModel 对象"""
        global_model = GlobalModel(
            id=global_model_dict["id"],
            name=global_model_dict["name"],
            display_name=global_model_dict.get("display_name"),
            default_supports_vision=global_model_dict.get("default_supports_vision", False),
            default_supports_function_calling=global_model_dict.get("default_supports_function_calling", False),
            default_supports_streaming=global_model_dict.get("default_supports_streaming", True),
            default_supports_extended_thinking=global_model_dict.get("default_supports_extended_thinking", False),
            default_supports_image_generation=global_model_dict.get("default_supports_image_generation", False),
            is_active=global_model_dict.get("is_active", True),
            description=global_model_dict.get("description"),
        )
        return global_model
