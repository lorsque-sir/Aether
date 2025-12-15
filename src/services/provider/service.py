"""
提供商服务
负责提供商选择、模型映射和请求处理
"""

from typing import Dict

from sqlalchemy.orm import Session

from src.models.database import GlobalModel, Model, Provider
from src.services.model.cost import ModelCostService
from src.services.model.mapper import ModelMapperMiddleware, ModelRoutingMiddleware


class ProviderService:
    """提供商服务类"""

    def __init__(self, db: Session):
        """
        初始化提供商服务

        Args:
            db: 数据库会话
        """
        self.db = db
        self.mapper = ModelMapperMiddleware(db)
        self.router = ModelRoutingMiddleware(db)
        self.cost_service = ModelCostService(db)

    async def _check_model_availability(self, model_name: str):
        """
        检查模型是否可用（严格白名单模式）

        Args:
            model_name: 模型名称（必须是 GlobalModel.name）

        Returns:
            Model对象如果存在且激活，否则None
        """
        # 直接查找 GlobalModel
        global_model = (
            self.db.query(GlobalModel)
            .filter(GlobalModel.name == model_name, GlobalModel.is_active == True)
            .first()
        )

        if global_model:
            # 查找任意 Provider 的 Model 实现
            model_obj = (
                self.db.query(Model)
                .filter(Model.global_model_id == global_model.id, Model.is_active == True)
                .first()
            )
            if model_obj:
                return model_obj

        return None

    async def _check_provider_model_availability(self, provider_id: str, model_name: str):
        """
        检查特定提供商是否支持特定模型

        Args:
            provider_id: 提供商ID
            model_name: 模型名称（必须是 GlobalModel.name）

        Returns:
            Model对象如果该提供商支持该模型且激活，否则None
        """
        # 直接查找 GlobalModel
        global_model = (
            self.db.query(GlobalModel)
            .filter(GlobalModel.name == model_name, GlobalModel.is_active == True)
            .first()
        )

        if global_model:
            # 查找该 Provider 是否有实现该 GlobalModel
            model_obj = (
                self.db.query(Model)
                .filter(
                    Model.provider_id == provider_id,
                    Model.global_model_id == global_model.id,
                    Model.is_active == True,
                )
                .first()
            )
            if model_obj:
                return model_obj

        return None

    def calculate_cost(
        self, provider: Provider, model: str, input_tokens: int, output_tokens: int
    ) -> Dict[str, float]:
        """
        计算使用成本

        Args:
            provider: 提供商对象
            model: 模型名
            input_tokens: 输入tokens
            output_tokens: 输出tokens

        Returns:
            成本信息
        """
        return self.mapper.calculate_cost(model, provider.id, input_tokens, output_tokens)

    def get_available_models(self) -> Dict[str, list]:
        """
        获取所有可用的模型

        Returns:
            字典，键为模型名，值为提供商列表
        """
        return self.router.get_available_models()

    def select_provider(self, model_name: str, preferred_provider=None):
        """
        选择提供商

        Args:
            model_name: 模型名
            preferred_provider: 首选提供商

        Returns:
            Provider对象
        """
        return self.router.select_provider(model_name, preferred_provider)
