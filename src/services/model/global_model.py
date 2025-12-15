"""
GlobalModel 服务层

提供 GlobalModel 的 CRUD 操作、查询和统计功能
"""

from typing import Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session, joinedload

from src.core.exceptions import InvalidRequestException, NotFoundException
from src.core.logger import logger
from src.models.database import GlobalModel, Model
from src.models.pydantic_models import GlobalModelUpdate



class GlobalModelService:
    """GlobalModel 服务"""

    @staticmethod
    def get_global_model(db: Session, global_model_id: str) -> GlobalModel:
        """
        获取单个 GlobalModel

        Args:
            global_model_id: GlobalModel 的 UUID 或 name
        """
        # 先尝试通过 ID 查找
        global_model = db.query(GlobalModel).filter(GlobalModel.id == global_model_id).first()

        # 如果没找到，尝试通过 name 查找
        if not global_model:
            global_model = db.query(GlobalModel).filter(GlobalModel.name == global_model_id).first()

        if not global_model:
            raise NotFoundException(f"GlobalModel {global_model_id} not found")
        return global_model

    @staticmethod
    def get_global_model_by_name(db: Session, name: str) -> Optional[GlobalModel]:
        """通过名称获取 GlobalModel"""
        return db.query(GlobalModel).filter(GlobalModel.name == name).first()

    @staticmethod
    def list_global_models(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> List[GlobalModel]:
        """列出 GlobalModel"""
        query = db.query(GlobalModel)

        if is_active is not None:
            query = query.filter(GlobalModel.is_active == is_active)

        if search:
            search_pattern = f"%{search}%"
            query = query.filter(
                (GlobalModel.name.ilike(search_pattern))
                | (GlobalModel.display_name.ilike(search_pattern))
                | (GlobalModel.description.ilike(search_pattern))
            )

        # 按名称排序
        query = query.order_by(GlobalModel.name)

        return query.offset(skip).limit(limit).all()

    @staticmethod
    def create_global_model(
        db: Session,
        name: str,
        display_name: str,
        description: Optional[str] = None,
        official_url: Optional[str] = None,
        icon_url: Optional[str] = None,
        is_active: Optional[bool] = True,
        # 按次计费配置
        default_price_per_request: Optional[float] = None,
        # 阶梯计费配置（必填）
        default_tiered_pricing: dict = None,
        # 默认能力配置
        default_supports_vision: Optional[bool] = None,
        default_supports_function_calling: Optional[bool] = None,
        default_supports_streaming: Optional[bool] = None,
        default_supports_extended_thinking: Optional[bool] = None,
        # Key 能力配置
        supported_capabilities: Optional[List[str]] = None,
    ) -> GlobalModel:
        """创建 GlobalModel"""
        # 检查名称是否已存在
        existing = GlobalModelService.get_global_model_by_name(db, name)
        if existing:
            raise InvalidRequestException(f"GlobalModel with name '{name}' already exists")

        global_model = GlobalModel(
            name=name,
            display_name=display_name,
            description=description,
            official_url=official_url,
            icon_url=icon_url,
            is_active=is_active,
            # 按次计费配置
            default_price_per_request=default_price_per_request,
            # 阶梯计费配置
            default_tiered_pricing=default_tiered_pricing,
            # 默认能力配置
            default_supports_vision=default_supports_vision,
            default_supports_function_calling=default_supports_function_calling,
            default_supports_streaming=default_supports_streaming,
            default_supports_extended_thinking=default_supports_extended_thinking,
            # Key 能力配置
            supported_capabilities=supported_capabilities,
        )

        db.add(global_model)
        db.commit()
        db.refresh(global_model)

        return global_model

    @staticmethod
    def update_global_model(
        db: Session,
        global_model_id: str,
        update_data: GlobalModelUpdate,
    ) -> GlobalModel:
        """
        更新 GlobalModel

        使用 exclude_unset=True 来区分"未提供字段"和"显式设置为 None"：
        - 未提供的字段不会被更新
        - 显式设置为 None 的字段会被更新为 None（置空）
        """
        global_model = GlobalModelService.get_global_model(db, global_model_id)

        # 只更新显式设置的字段（包括显式设置为 None 的情况）
        data_dict = update_data.model_dump(exclude_unset=True)

        # 处理阶梯计费配置：如果是 TieredPricingConfig 对象，转换为 dict
        if "default_tiered_pricing" in data_dict:
            tiered_pricing = data_dict["default_tiered_pricing"]
            if tiered_pricing is not None and hasattr(tiered_pricing, "model_dump"):
                data_dict["default_tiered_pricing"] = tiered_pricing.model_dump()

        for field, value in data_dict.items():
            setattr(global_model, field, value)

        db.commit()
        db.refresh(global_model)

        return global_model

    @staticmethod
    def delete_global_model(db: Session, global_model_id: str) -> None:
        """
        删除 GlobalModel

        默认行为: 级联删除所有关联的 Provider 模型实现
        """
        global_model = GlobalModelService.get_global_model(db, global_model_id)

        # 查找所有关联的 Model（使用 global_model.id，预加载 provider 关联）
        associated_models = (
            db.query(Model)
            .options(joinedload(Model.provider))
            .filter(Model.global_model_id == global_model.id)
            .all()
        )

        # 级联删除所有关联的 Provider 模型实现
        if associated_models:
            logger.info(f"删除 GlobalModel {global_model.name} 的 {len(associated_models)} 个关联 Provider 模型")
            for model in associated_models:
                db.delete(model)

        # 删除 GlobalModel
        db.delete(global_model)
        db.commit()

    @staticmethod
    def get_global_model_stats(db: Session, global_model_id: str) -> Dict:
        """获取 GlobalModel 统计信息"""
        global_model = GlobalModelService.get_global_model(db, global_model_id)

        # 统计关联的 Model 数量（使用 global_model.id，预加载 provider 关联）
        models = (
            db.query(Model)
            .options(joinedload(Model.provider))
            .filter(Model.global_model_id == global_model.id)
            .all()
        )

        # 统计支持的 Provider 数量
        provider_ids = set(model.provider_id for model in models)

        # 从阶梯计费中提取价格范围
        input_prices = []
        output_prices = []
        for m in models:
            tiered = m.get_effective_tiered_pricing()
            if tiered and tiered.get("tiers"):
                first_tier = tiered["tiers"][0]
                if first_tier.get("input_price_per_1m") is not None:
                    input_prices.append(first_tier["input_price_per_1m"])
                if first_tier.get("output_price_per_1m") is not None:
                    output_prices.append(first_tier["output_price_per_1m"])

        return {
            "global_model_id": global_model.id,
            "name": global_model.name,
            "total_models": len(models),
            "total_providers": len(provider_ids),
            "price_range": {
                "min_input": min(input_prices) if input_prices else None,
                "max_input": max(input_prices) if input_prices else None,
                "min_output": min(output_prices) if output_prices else None,
                "max_output": max(output_prices) if output_prices else None,
            },
        }

    @staticmethod
    def batch_assign_to_providers(
        db: Session,
        global_model_id: str,
        provider_ids: List[str],
        create_models: bool = False,
    ) -> Dict:
        """批量为多个 Provider 添加 GlobalModel 实现"""
        from .service import ModelService

        global_model = GlobalModelService.get_global_model(db, global_model_id)

        results = {
            "success": [],
            "errors": [],
        }

        for provider_id in provider_ids:
            try:
                # 检查该 Provider 是否已有该 GlobalModel 的实现（使用 global_model.id）
                existing_model = (
                    db.query(Model)
                    .filter(
                        Model.provider_id == provider_id,
                        Model.global_model_id == global_model.id,
                    )
                    .first()
                )

                if existing_model:
                    results["errors"].append(
                        {
                            "provider_id": provider_id,
                            "error": "Model already exists for this provider",
                        }
                    )
                    continue

                if create_models:
                    # 创建新的 Model（价格和能力设为 None，继承 GlobalModel 默认值）
                    model = Model(
                        provider_id=provider_id,
                        global_model_id=global_model.id,
                        provider_model_name=global_model.name,  # 默认使用 GlobalModel name
                        # 计费设为 None，使用 GlobalModel 默认值
                        price_per_request=None,
                        tiered_pricing=None,
                        # 能力设为 None，使用 GlobalModel 默认值
                        supports_vision=None,
                        supports_function_calling=None,
                        supports_streaming=None,
                        supports_extended_thinking=None,
                        is_active=True,
                    )
                    db.add(model)
                    db.commit()

                    results["success"].append(
                        {"provider_id": provider_id, "model_id": model.id, "created": True}
                    )
                else:
                    results["errors"].append(
                        {
                            "provider_id": provider_id,
                            "error": "create_models=False, no existing model found",
                        }
                    )

            except Exception as e:
                db.rollback()
                results["errors"].append({"provider_id": provider_id, "error": str(e)})

        db.commit()
        return results
