"""
用量统计和配额管理服务
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.core.enums import ProviderBillingType
from src.core.logger import logger
from src.models.database import ApiKey, Provider, ProviderAPIKey, Usage, User, UserRole
from src.services.model.cost import ModelCostService
from src.services.system.config import SystemConfigService



class UsageService:
    """用量统计服务"""

    @classmethod
    async def get_model_price_async(
        cls, db: Session, provider: str, model: str
    ) -> tuple[float, float]:
        """异步获取模型价格（输入价格，输出价格）每1M tokens

        新架构查找逻辑：
        1. 使用 ModelMappingResolver 解析别名（如果是）
        2. 解析为 GlobalModel.name
        3. 查找该 Provider 的 Model 实现并获取价格
        4. 如果找不到则使用系统默认价格
        """

        service = ModelCostService(db)
        return await service.get_model_price_async(provider, model)

    @classmethod
    def get_model_price(cls, db: Session, provider: str, model: str) -> tuple[float, float]:
        """获取模型价格（输入价格，输出价格）每1M tokens

        新架构查找逻辑：
        1. 使用 ModelMappingResolver 解析别名（如果是）
        2. 解析为 GlobalModel.name
        3. 查找该 Provider 的 Model 实现并获取价格
        4. 如果找不到则使用系统默认价格
        """

        service = ModelCostService(db)
        return service.get_model_price(provider, model)

    @classmethod
    async def get_cache_prices_async(
        cls, db: Session, provider: str, model: str, input_price: float
    ) -> tuple[float, float]:
        """异步获取模型缓存价格（缓存创建价格，缓存读取价格）每1M tokens"""
        service = ModelCostService(db)
        return await service.get_cache_prices_async(provider, model, input_price)

    @classmethod
    def get_cache_prices(
        cls, db: Session, provider: str, model: str, input_price: float
    ) -> tuple[float, float]:
        """获取模型缓存价格（缓存创建价格，缓存读取价格）每1M tokens"""
        service = ModelCostService(db)
        return service.get_cache_prices(provider, model, input_price)

    @classmethod
    async def get_request_price_async(
        cls, db: Session, provider: str, model: str
    ) -> Optional[float]:
        """异步获取模型按次计费价格"""
        service = ModelCostService(db)
        return await service.get_request_price_async(provider, model)

    @classmethod
    def get_request_price(cls, db: Session, provider: str, model: str) -> Optional[float]:
        """获取模型按次计费价格"""
        service = ModelCostService(db)
        return service.get_request_price(provider, model)

    @staticmethod
    def calculate_cost(
        input_tokens: int,
        output_tokens: int,
        input_price_per_1m: float,
        output_price_per_1m: float,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        cache_creation_price_per_1m: Optional[float] = None,
        cache_read_price_per_1m: Optional[float] = None,
        price_per_request: Optional[float] = None,
    ) -> tuple[float, float, float, float, float, float, float]:
        """计算成本（价格是每百万tokens）- 固定价格模式

        Returns:
            Tuple of (input_cost, output_cost, cache_creation_cost,
                     cache_read_cost, cache_cost, request_cost, total_cost)
        """
        return ModelCostService.compute_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_price_per_1m=input_price_per_1m,
            output_price_per_1m=output_price_per_1m,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_price_per_1m=cache_creation_price_per_1m,
            cache_read_price_per_1m=cache_read_price_per_1m,
            price_per_request=price_per_request,
        )

    @classmethod
    async def calculate_cost_with_strategy_async(
        cls,
        db: Session,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        api_format: Optional[str] = None,
        cache_ttl_minutes: Optional[int] = None,
    ) -> tuple[float, float, float, float, float, float, float, Optional[int]]:
        """使用策略模式计算成本（支持阶梯计费）

        根据 api_format 选择对应的计费策略，支持阶梯计费和 TTL 差异化。

        Returns:
            Tuple of (input_cost, output_cost, cache_creation_cost,
                     cache_read_cost, cache_cost, request_cost, total_cost, tier_index)
        """
        service = ModelCostService(db)
        return await service.compute_cost_with_strategy_async(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            api_format=api_format,
            cache_ttl_minutes=cache_ttl_minutes,
        )

    @classmethod
    async def record_usage_async(
        cls,
        db: Session,
        user: Optional[User],
        api_key: Optional[ApiKey],
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        request_type: str = "chat",
        api_format: Optional[str] = None,
        is_stream: bool = False,
        response_time_ms: Optional[int] = None,
        status_code: int = 200,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_headers: Optional[Dict[str, Any]] = None,
        request_body: Optional[Any] = None,
        provider_request_headers: Optional[Dict[str, Any]] = None,  # 向提供商发送的请求头
        response_headers: Optional[Dict[str, Any]] = None,
        response_body: Optional[Any] = None,
        request_id: Optional[str] = None,  # 请求ID，如果未提供则自动生成
        # Provider 侧追踪信息（记录最终成功的 Provider/Endpoint/Key）
        provider_id: Optional[str] = None,
        provider_endpoint_id: Optional[str] = None,
        provider_api_key_id: Optional[str] = None,
        # 请求状态 (pending, streaming, completed, failed)
        status: str = "completed",
        # 阶梯计费相关参数
        cache_ttl_minutes: Optional[int] = None,  # 缓存时长（用于 TTL 差异化定价）
        use_tiered_pricing: bool = True,  # 是否使用阶梯计费（默认启用）
        # 模型映射信息
        target_model: Optional[str] = None,  # 映射后的目标模型名
    ) -> Usage:
        """异步记录使用量（支持阶梯计费）"""

        # 使用传入的 request_id 或生成新的
        if request_id is None:
            request_id = str(uuid.uuid4())[:8]  # 生成8位短ID以保持一致性

        # 如果提供了 provider_api_key_id，从数据库查询 rate_multiplier
        actual_rate_multiplier = 1.0  # 默认值
        if provider_api_key_id:
            provider_key = (
                db.query(ProviderAPIKey).filter(ProviderAPIKey.id == provider_api_key_id).first()
            )
            if provider_key and provider_key.rate_multiplier:
                actual_rate_multiplier = provider_key.rate_multiplier

        # 失败的请求不应该计入按次计费费用
        is_failed_request = status_code >= 400 or error_message is not None

        # 获取模型价格信息（用于历史记录）
        input_price, output_price = await cls.get_model_price_async(db, provider, model)
        cache_creation_price, cache_read_price = await cls.get_cache_prices_async(
            db, provider, model, input_price
        )
        request_price = await cls.get_request_price_async(db, provider, model)
        effective_request_price = None if is_failed_request else request_price

        # 初始化成本变量（避免 `in locals()` 反模式）
        input_cost = 0.0
        output_cost = 0.0
        cache_creation_cost = 0.0
        cache_read_cost = 0.0
        cache_cost = 0.0
        request_cost = 0.0
        total_cost = 0.0
        tier_index = None

        # 计算成本（支持阶梯计费）
        if use_tiered_pricing:
            # 使用策略模式计算成本（支持阶梯计费和 TTL 差异化）
            (
                input_cost,
                output_cost,
                cache_creation_cost,
                cache_read_cost,
                cache_cost,
                request_cost,
                total_cost,
                tier_index,
            ) = await cls.calculate_cost_with_strategy_async(
                db=db,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                api_format=api_format,
                cache_ttl_minutes=cache_ttl_minutes,
            )
            # 如果失败请求，重置按次费用
            if is_failed_request:
                total_cost = total_cost - request_cost
                request_cost = 0.0
        else:
            # 使用固定价格模式
            (
                input_cost,
                output_cost,
                cache_creation_cost,
                cache_read_cost,
                cache_cost,
                request_cost,
                total_cost,
            ) = cls.calculate_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_price_per_1m=input_price,
                output_price_per_1m=output_price,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                cache_creation_price_per_1m=cache_creation_price,
                cache_read_price_per_1m=cache_read_price,
                price_per_request=effective_request_price,
            )

        # 根据配置决定是否记录请求详情
        should_log_headers = SystemConfigService.should_log_headers(db)
        should_log_body = SystemConfigService.should_log_body(db)

        # 处理请求头（可能需要脱敏）
        processed_request_headers = None
        if should_log_headers and request_headers:
            processed_request_headers = SystemConfigService.mask_sensitive_headers(
                db, request_headers
            )

        # 处理提供商请求头（可能需要脱敏）
        processed_provider_request_headers = None
        if should_log_headers and provider_request_headers:
            processed_provider_request_headers = SystemConfigService.mask_sensitive_headers(
                db, provider_request_headers
            )

        # 处理请求体和响应体（可能需要截断）
        processed_request_body = None
        processed_response_body = None
        if should_log_body:
            if request_body:
                processed_request_body = SystemConfigService.truncate_body(
                    db, request_body, is_request=True
                )
            if response_body:
                processed_response_body = SystemConfigService.truncate_body(
                    db, response_body, is_request=False
                )

        # 处理响应头
        processed_response_headers = None
        if should_log_headers and response_headers:
            processed_response_headers = SystemConfigService.mask_sensitive_headers(
                db, response_headers
            )

        # 检查 Provider 的计费类型，免费套餐的实际费用为 0
        is_free_tier = False
        if provider_id:
            provider_obj = db.query(Provider).filter(Provider.id == provider_id).first()
            if provider_obj and provider_obj.billing_type == ProviderBillingType.FREE_TIER:
                is_free_tier = True

        # 计算真实成本（表面成本 × 倍率），免费套餐实际费用为 0
        if is_free_tier:
            actual_input_cost = 0.0
            actual_output_cost = 0.0
            actual_cache_creation_cost = 0.0
            actual_cache_read_cost = 0.0
            actual_request_cost = 0.0
            actual_total_cost = 0.0
        else:
            actual_input_cost = input_cost * actual_rate_multiplier
            actual_output_cost = output_cost * actual_rate_multiplier
            actual_cache_creation_cost = cache_creation_cost * actual_rate_multiplier
            actual_cache_read_cost = cache_read_cost * actual_rate_multiplier
            actual_request_cost = request_cost * actual_rate_multiplier
            actual_total_cost = total_cost * actual_rate_multiplier

        # 记录使用量
        usage = Usage(
            user_id=user.id if user else None,
            api_key_id=api_key.id if api_key else None,
            request_id=request_id,
            provider=provider,
            model=model,
            target_model=target_model,  # 映射后的目标模型名
            # Provider 侧追踪信息
            provider_id=provider_id,
            provider_endpoint_id=provider_endpoint_id,
            provider_api_key_id=provider_api_key_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            cache_cost_usd=cache_cost,
            cache_creation_cost_usd=cache_creation_cost,
            cache_read_cost_usd=cache_read_cost,
            request_cost_usd=request_cost,
            total_cost_usd=total_cost,
            # 真实成本（考虑倍率）
            actual_input_cost_usd=actual_input_cost,
            actual_output_cost_usd=actual_output_cost,
            actual_cache_creation_cost_usd=actual_cache_creation_cost,
            actual_cache_read_cost_usd=actual_cache_read_cost,
            actual_request_cost_usd=actual_request_cost,
            actual_total_cost_usd=actual_total_cost,
            rate_multiplier=actual_rate_multiplier,  # 使用实际查询到的 rate_multiplier
            # 添加历史价格信息
            input_price_per_1m=input_price,
            output_price_per_1m=output_price,
            cache_creation_price_per_1m=cache_creation_price,
            cache_read_price_per_1m=cache_read_price,
            price_per_request=request_price,
            request_type=request_type,
            api_format=api_format,
            is_stream=is_stream,
            status_code=status_code,
            error_message=error_message,
            response_time_ms=response_time_ms,
            status=status,  # 请求状态追踪
            request_metadata=metadata,
            request_headers=processed_request_headers,
            request_body=processed_request_body,
            provider_request_headers=processed_provider_request_headers,
            response_headers=processed_response_headers,
            response_body=processed_response_body,
        )

        db.add(usage)

        # 更新 GlobalModel 使用计数（原子操作）
        from sqlalchemy import update

        from src.models.database import GlobalModel

        db.execute(
            update(GlobalModel)
            .where(GlobalModel.name == model)
            .values(usage_count=GlobalModel.usage_count + 1)
        )

        # 更新 Provider 月度使用量（原子操作）- 使用实际费用（免费套餐为 0）
        if provider_id:
            db.execute(
                update(Provider)
                .where(Provider.id == provider_id)
                .values(monthly_used_usd=Provider.monthly_used_usd + actual_total_cost)
            )

        db.commit()  # 立即提交事务,释放数据库锁
        # 不需要 refresh，commit 后对象已经有数据库生成的值

        return usage

    @classmethod
    async def record_usage(
        cls,
        db: Session,
        user: Optional[User],
        api_key: Optional[ApiKey],
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        request_type: str = "chat",
        api_format: Optional[str] = None,
        is_stream: bool = False,
        response_time_ms: Optional[int] = None,
        status_code: int = 200,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_headers: Optional[Dict[str, Any]] = None,
        request_body: Optional[Any] = None,
        provider_request_headers: Optional[Dict[str, Any]] = None,
        response_headers: Optional[Dict[str, Any]] = None,
        response_body: Optional[Any] = None,
        request_id: Optional[str] = None,  # 请求ID，如果未提供则自动生成
        # Provider 侧追踪信息（记录最终成功的 Provider/Endpoint/Key）
        provider_id: Optional[str] = None,
        provider_endpoint_id: Optional[str] = None,
        provider_api_key_id: Optional[str] = None,
        # 请求状态 (pending, streaming, completed, failed)
        status: str = "completed",
        # 阶梯计费相关参数
        cache_ttl_minutes: Optional[int] = None,  # 缓存时长（用于 TTL 差异化定价）
        use_tiered_pricing: bool = True,  # 是否使用阶梯计费（默认启用）
        # 模型映射信息
        target_model: Optional[str] = None,  # 映射后的目标模型名
    ) -> Usage:
        """记录使用量（支持阶梯计费）"""

        # 使用传入的 request_id 或生成新的
        if request_id is None:
            request_id = str(uuid.uuid4())[:8]  # 生成8位短ID以保持一致性

        # 如果提供了 provider_api_key_id，从数据库查询 rate_multiplier
        actual_rate_multiplier = 1.0  # 默认值
        if provider_api_key_id:
            provider_key = (
                db.query(ProviderAPIKey).filter(ProviderAPIKey.id == provider_api_key_id).first()
            )
            if provider_key and provider_key.rate_multiplier:
                actual_rate_multiplier = provider_key.rate_multiplier

        # 失败的请求不应该计入按次计费费用
        is_failed_request = status_code >= 400 or error_message is not None

        # 获取模型价格信息（用于历史记录）
        input_price, output_price = await cls.get_model_price_async(db, provider, model)
        cache_creation_price, cache_read_price = await cls.get_cache_prices_async(
            db, provider, model, input_price
        )
        request_price = await cls.get_request_price_async(db, provider, model)
        effective_request_price = None if is_failed_request else request_price

        # 初始化成本变量（避免 `in locals()` 反模式）
        input_cost = 0.0
        output_cost = 0.0
        cache_creation_cost = 0.0
        cache_read_cost = 0.0
        cache_cost = 0.0
        request_cost = 0.0
        total_cost = 0.0

        # 计算成本（支持阶梯计费）
        if use_tiered_pricing:
            # 使用策略模式计算成本（支持阶梯计费和 TTL 差异化）
            (
                input_cost,
                output_cost,
                cache_creation_cost,
                cache_read_cost,
                cache_cost,
                request_cost,
                total_cost,
                _tier_index,
            ) = await cls.calculate_cost_with_strategy_async(
                db=db,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                api_format=api_format,
                cache_ttl_minutes=cache_ttl_minutes,
            )
            # 如果失败请求，重置按次费用
            if is_failed_request:
                total_cost = total_cost - request_cost
                request_cost = 0.0
        else:
            # 使用固定价格模式
            (
                input_cost,
                output_cost,
                cache_creation_cost,
                cache_read_cost,
                cache_cost,
                request_cost,
                total_cost,
            ) = cls.calculate_cost(
                input_tokens,
                output_tokens,
                input_price,
                output_price,
                cache_creation_input_tokens,
                cache_read_input_tokens,
                cache_creation_price,
                cache_read_price,
                effective_request_price,
            )

        # 根据配置决定是否记录请求详情
        should_log_headers = SystemConfigService.should_log_headers(db)
        should_log_body = SystemConfigService.should_log_body(db)

        # 处理请求头（可能需要脱敏）
        processed_request_headers = None
        if should_log_headers and request_headers:
            processed_request_headers = SystemConfigService.mask_sensitive_headers(
                db, request_headers
            )

        # 处理提供商请求头（可能需要脱敏）
        processed_provider_request_headers = None
        if should_log_headers and provider_request_headers:
            processed_provider_request_headers = SystemConfigService.mask_sensitive_headers(
                db, provider_request_headers
            )

        # 处理请求体和响应体（可能需要截断）
        processed_request_body = None
        processed_response_body = None
        if should_log_body:
            if request_body:
                processed_request_body = SystemConfigService.truncate_body(
                    db, request_body, is_request=True
                )
            if response_body:
                processed_response_body = SystemConfigService.truncate_body(
                    db, response_body, is_request=False
                )

        # 处理响应头
        processed_response_headers = None
        if should_log_headers and response_headers:
            processed_response_headers = SystemConfigService.mask_sensitive_headers(
                db, response_headers
            )

        # 检查 Provider 的计费类型，免费套餐的实际费用为 0
        is_free_tier = False
        if provider_id:
            provider_obj = db.query(Provider).filter(Provider.id == provider_id).first()
            if provider_obj and provider_obj.billing_type == ProviderBillingType.FREE_TIER:
                is_free_tier = True

        # 计算真实成本（表面成本 × 倍率），免费套餐实际费用为 0
        if is_free_tier:
            actual_input_cost = 0.0
            actual_output_cost = 0.0
            actual_cache_creation_cost = 0.0
            actual_cache_read_cost = 0.0
            actual_request_cost = 0.0
            actual_total_cost = 0.0
        else:
            actual_input_cost = input_cost * actual_rate_multiplier
            actual_output_cost = output_cost * actual_rate_multiplier
            actual_cache_creation_cost = cache_creation_cost * actual_rate_multiplier
            actual_cache_read_cost = cache_read_cost * actual_rate_multiplier
            actual_request_cost = request_cost * actual_rate_multiplier
            actual_total_cost = total_cost * actual_rate_multiplier

        # 创建使用记录
        usage = Usage(
            user_id=user.id if user else None,
            api_key_id=api_key.id if api_key else None,
            request_id=request_id,
            provider=provider,
            model=model,
            target_model=target_model,  # 映射后的目标模型名
            # Provider 侧追踪信息
            provider_id=provider_id,
            provider_endpoint_id=provider_endpoint_id,
            provider_api_key_id=provider_api_key_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            cache_cost_usd=cache_cost,
            cache_creation_cost_usd=cache_creation_cost,
            cache_read_cost_usd=cache_read_cost,
            request_cost_usd=request_cost,
            total_cost_usd=total_cost,
            # 真实成本（考虑倍率）
            actual_input_cost_usd=actual_input_cost,
            actual_output_cost_usd=actual_output_cost,
            actual_cache_creation_cost_usd=actual_cache_creation_cost,
            actual_cache_read_cost_usd=actual_cache_read_cost,
            actual_request_cost_usd=actual_request_cost,
            actual_total_cost_usd=actual_total_cost,
            rate_multiplier=actual_rate_multiplier,  # 使用实际查询到的 rate_multiplier
            # 添加历史价格信息
            input_price_per_1m=input_price,
            output_price_per_1m=output_price,
            cache_creation_price_per_1m=cache_creation_price,
            cache_read_price_per_1m=cache_read_price,
            price_per_request=request_price,
            request_type=request_type,
            api_format=api_format,
            is_stream=is_stream,
            status_code=status_code,
            error_message=error_message,
            response_time_ms=response_time_ms,
            status=status,  # 请求状态追踪
            request_metadata=metadata,
            request_headers=processed_request_headers,
            request_body=processed_request_body,
            provider_request_headers=processed_provider_request_headers,
            response_headers=processed_response_headers,
            response_body=processed_response_body,
        )

        # 检查是否已存在相同 request_id 的记录（用于更新 pending 记录或防止重试时重复插入）
        existing_usage = db.query(Usage).filter(Usage.request_id == request_id).first()
        if existing_usage:
            # 已存在记录，更新而非插入
            logger.debug(f"request_id {request_id} 已存在，更新现有记录 (status: {existing_usage.status} -> {status})")
            # 更新关键字段
            existing_usage.provider = provider  # 更新 provider 名称
            existing_usage.status = status
            existing_usage.status_code = status_code
            existing_usage.error_message = error_message
            existing_usage.response_time_ms = response_time_ms
            # 更新请求头和请求体（如果有新值）
            if processed_request_headers is not None:
                existing_usage.request_headers = processed_request_headers
            if processed_request_body is not None:
                existing_usage.request_body = processed_request_body
            if processed_provider_request_headers is not None:
                existing_usage.provider_request_headers = processed_provider_request_headers
            existing_usage.response_body = processed_response_body
            existing_usage.response_headers = processed_response_headers
            # 更新 token 和费用信息
            existing_usage.input_tokens = input_tokens
            existing_usage.output_tokens = output_tokens
            existing_usage.total_tokens = input_tokens + output_tokens
            existing_usage.cache_creation_input_tokens = cache_creation_input_tokens
            existing_usage.cache_read_input_tokens = cache_read_input_tokens
            existing_usage.input_cost_usd = input_cost
            existing_usage.output_cost_usd = output_cost
            existing_usage.cache_cost_usd = cache_cost
            existing_usage.cache_creation_cost_usd = cache_creation_cost
            existing_usage.cache_read_cost_usd = cache_read_cost
            existing_usage.request_cost_usd = request_cost
            existing_usage.total_cost_usd = total_cost
            existing_usage.actual_input_cost_usd = actual_input_cost
            existing_usage.actual_output_cost_usd = actual_output_cost
            existing_usage.actual_cache_creation_cost_usd = actual_cache_creation_cost
            existing_usage.actual_cache_read_cost_usd = actual_cache_read_cost
            existing_usage.actual_request_cost_usd = actual_request_cost
            existing_usage.actual_total_cost_usd = actual_total_cost
            existing_usage.rate_multiplier = actual_rate_multiplier
            # 更新 Provider 侧追踪信息
            existing_usage.provider_id = provider_id
            existing_usage.provider_endpoint_id = provider_endpoint_id
            existing_usage.provider_api_key_id = provider_api_key_id
            # 更新模型映射信息
            if target_model is not None:
                existing_usage.target_model = target_model
            # 不需要 db.add，已在会话中
            usage = existing_usage
        else:
            db.add(usage)

        # 确保 user 和 api_key 在会话中（如果存在）
        if user and not db.object_session(user):
            user = db.merge(user)
        if api_key and not db.object_session(api_key):
            api_key = db.merge(api_key)

        # 使用原子更新避免并发竞态条件
        from sqlalchemy import func, update

        from src.models.database import ApiKey, User

        # 更新用户使用量（原子操作）- 使用实际费用（免费套餐为 0）
        # 独立Key不计入创建者的使用记录
        if user and not (api_key and api_key.is_standalone):
            db.execute(
                update(User)
                .where(User.id == user.id)
                .values(
                    used_usd=User.used_usd + actual_total_cost,
                    total_usd=User.total_usd + actual_total_cost,
                    updated_at=func.now(),
                )
            )

        # 更新API密钥使用量（原子操作）- 使用实际费用（免费套餐为 0）
        if api_key:
            # 独立余额Key需要扣除余额
            if api_key.is_standalone:
                db.execute(
                    update(ApiKey)
                    .where(ApiKey.id == api_key.id)
                    .values(
                        total_requests=ApiKey.total_requests + 1,
                        total_cost_usd=ApiKey.total_cost_usd + actual_total_cost,
                        balance_used_usd=ApiKey.balance_used_usd + actual_total_cost,
                        last_used_at=func.now(),
                        updated_at=func.now(),
                    )
                )
            else:
                # 普通Key只更新统计信息，不扣除余额
                db.execute(
                    update(ApiKey)
                    .where(ApiKey.id == api_key.id)
                    .values(
                        total_requests=ApiKey.total_requests + 1,
                        total_cost_usd=ApiKey.total_cost_usd + actual_total_cost,
                        last_used_at=func.now(),
                        updated_at=func.now(),
                    )
                )

        # 更新 GlobalModel 使用计数（原子操作）
        from src.models.database import GlobalModel

        db.execute(
            update(GlobalModel)
            .where(GlobalModel.name == model)
            .values(usage_count=GlobalModel.usage_count + 1)
        )

        # 更新 Provider 月度使用量（原子操作）- 使用实际费用（免费套餐为 0）
        if provider_id:
            db.execute(
                update(Provider)
                .where(Provider.id == provider_id)
                .values(monthly_used_usd=Provider.monthly_used_usd + actual_total_cost)
            )

        # 提交事务到数据库
        try:
            db.commit()  # 立即提交事务,释放数据库锁

            # 使用 expire 标记对象过期，下次访问时自动重新加载（避免死锁）
            # 不在热路径上立即 refresh，避免行锁等待
            # db.expire(usage)
            # if user:
            #     db.expire(user)
            # if api_key:
            #     db.expire(api_key)

        except Exception as e:
            logger.error(f"提交使用记录时出错: {e}")
            db.rollback()
            raise

        # 不再记录重复的性能日志和访问日志，因为已经在完成日志中输出了
        # 这些信息都包含在 request_orchestrator.py 的完成日志中

        return usage

    @staticmethod
    def check_user_quota(
        db: Session,
        user: User,
        estimated_tokens: int = 0,
        estimated_cost: float = 0,
        api_key: Optional[ApiKey] = None,
    ) -> tuple[bool, str]:
        """检查用户配额或独立Key余额

        Args:
            db: 数据库会话
            user: 用户对象
            estimated_tokens: 预估token数
            estimated_cost: 预估费用
            api_key: API Key对象（用于检查独立余额Key）

        Returns:
            (是否通过, 消息)
        """

        # 如果是独立余额Key，检查Key的余额而不是用户配额
        if api_key and api_key.is_standalone:
            # 导入 ApiKeyService 以使用统一的余额计算方法
            from src.services.user.apikey import ApiKeyService

            # NULL 表示无限制
            if api_key.current_balance_usd is None:
                return True, "OK"

            # 使用统一的余额计算方法
            remaining_balance = ApiKeyService.get_remaining_balance(api_key)
            if remaining_balance is None:
                return True, "OK"

            # 检查余额是否充足
            if remaining_balance < estimated_cost:
                return (
                    False,
                    f"Key余额不足（剩余: ${remaining_balance:.2f}，需要: ${estimated_cost:.2f}）",
                )

            return True, "OK"

        # 普通Key：检查用户配额
        # 管理员无限制
        if user.role == UserRole.ADMIN:
            return True, "OK"

        # NULL 表示无限制
        if user.quota_usd is None:
            return True, "OK"

        # 有配额限制，检查是否超额
        if user.used_usd + estimated_cost > user.quota_usd:
            remaining = user.quota_usd - user.used_usd
            return False, f"配额不足（剩余: ${remaining:.2f}）"

        return True, "OK"

    @staticmethod
    def get_usage_summary(
        db: Session,
        user_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        group_by: str = "day",  # day, week, month
    ) -> List[Dict[str, Any]]:
        """获取使用汇总"""

        query = db.query(Usage)
        # 过滤掉 pending/streaming 状态的请求（尚未完成的请求不应计入统计）
        query = query.filter(Usage.status.notin_(["pending", "streaming"]))

        if user_id:
            query = query.filter(Usage.user_id == user_id)
        if api_key_id:
            query = query.filter(Usage.api_key_id == api_key_id)
        if start_date:
            query = query.filter(Usage.created_at >= start_date)
        if end_date:
            query = query.filter(Usage.created_at <= end_date)

        # 使用跨数据库兼容的日期函数
        from src.utils.database_helpers import date_trunc_portable

        # 检测数据库方言
        dialect = db.bind.dialect.name

        # 根据分组类型选择日期函数（兼容多种数据库）
        if group_by == "day":
            date_func = date_trunc_portable(dialect, "day", Usage.created_at)
        elif group_by == "week":
            date_func = date_trunc_portable(dialect, "week", Usage.created_at)
        elif group_by == "month":
            date_func = date_trunc_portable(dialect, "month", Usage.created_at)
        else:
            # 默认按天分组
            date_func = date_trunc_portable(dialect, "day", Usage.created_at)

        # 汇总查询
        summary = db.query(
            date_func.label("period"),
            Usage.provider,
            Usage.model,
            func.count(Usage.id).label("requests"),
            func.sum(Usage.input_tokens).label("input_tokens"),
            func.sum(Usage.output_tokens).label("output_tokens"),
            func.sum(Usage.total_tokens).label("total_tokens"),
            func.sum(Usage.total_cost_usd).label("total_cost_usd"),
            func.avg(Usage.response_time_ms).label("avg_response_time"),
        )

        if user_id:
            summary = summary.filter(Usage.user_id == user_id)
        if api_key_id:
            summary = summary.filter(Usage.api_key_id == api_key_id)
        if start_date:
            summary = summary.filter(Usage.created_at >= start_date)
        if end_date:
            summary = summary.filter(Usage.created_at <= end_date)

        summary = summary.group_by(date_func, Usage.provider, Usage.model).all()

        return [
            {
                "period": row.period,
                "provider": row.provider,
                "model": row.model,
                "requests": row.requests,
                "input_tokens": row.input_tokens,
                "output_tokens": row.output_tokens,
                "total_tokens": row.total_tokens,
                "total_cost_usd": float(row.total_cost_usd),
                "avg_response_time_ms": (
                    float(row.avg_response_time) if row.avg_response_time else 0
                ),
            }
            for row in summary
        ]

    @staticmethod
    def get_daily_activity(
        db: Session,
        user_id: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        window_days: int = 365,
        include_actual_cost: bool = False,
    ) -> Dict[str, Any]:
        """按天统计请求活跃度，用于渲染热力图。"""

        def ensure_timezone(value: datetime) -> datetime:
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)

        # 如果调用方未指定时间范围，则默认统计最近 window_days 天
        now = datetime.now(timezone.utc)
        end_dt = ensure_timezone(end_date) if end_date else now
        start_dt = (
            ensure_timezone(start_date) if start_date else end_dt - timedelta(days=window_days - 1)
        )

        # 对齐到自然日的开始/结束，避免遗漏边界数据
        start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)

        from src.utils.database_helpers import date_trunc_portable

        bind = db.get_bind()
        dialect = bind.dialect.name if bind is not None else "sqlite"
        day_bucket = date_trunc_portable(dialect, "day", Usage.created_at).label("day")

        columns = [
            day_bucket,
            func.count(Usage.id).label("requests"),
            func.sum(Usage.total_tokens).label("total_tokens"),
            func.sum(Usage.total_cost_usd).label("total_cost_usd"),
        ]

        if include_actual_cost:
            columns.append(func.sum(Usage.actual_total_cost_usd).label("actual_total_cost_usd"))

        query = db.query(*columns).filter(Usage.created_at >= start_dt, Usage.created_at <= end_dt)

        if user_id:
            query = query.filter(Usage.user_id == user_id)

        query = query.group_by(day_bucket).order_by(day_bucket)
        rows = query.all()

        def normalize_period(value) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value[:10]
            if isinstance(value, datetime):
                return value.date().isoformat()
            return str(value)

        aggregated: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            key = normalize_period(row.day)
            aggregated[key] = {
                "requests": int(row.requests or 0),
                "total_tokens": int(row.total_tokens or 0),
                "total_cost_usd": float(row.total_cost_usd or 0.0),
            }
            if include_actual_cost:
                aggregated[key]["actual_total_cost_usd"] = float(row.actual_total_cost_usd or 0.0)

        days: List[Dict[str, Any]] = []
        cursor = start_dt.date()
        end_date_only = end_dt.date()
        max_requests = 0

        while cursor <= end_date_only:
            iso_date = cursor.isoformat()
            stats = aggregated.get(iso_date, {})
            requests = stats.get("requests", 0)
            total_tokens = stats.get("total_tokens", 0)
            total_cost = stats.get("total_cost_usd", 0.0)

            entry: Dict[str, Any] = {
                "date": iso_date,
                "requests": requests,
                "total_tokens": total_tokens,
                "total_cost": total_cost,
            }

            if include_actual_cost:
                entry["actual_total_cost"] = stats.get("actual_total_cost_usd", 0.0)

            days.append(entry)
            max_requests = max(max_requests, requests)
            cursor += timedelta(days=1)

        return {
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
            "total_days": len(days),
            "max_requests": max_requests,
            "days": days,
        }

    @staticmethod
    def get_top_users(
        db: Session,
        limit: int = 10,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        order_by: str = "cost",  # cost, tokens, requests
    ) -> List[Dict[str, Any]]:
        """获取使用量最高的用户"""

        query = (
            db.query(
                User.id,
                User.email,
                User.username,
                func.count(Usage.id).label("requests"),
                func.sum(Usage.total_tokens).label("tokens"),
                func.sum(Usage.total_cost_usd).label("cost_usd"),
            )
            .join(Usage, User.id == Usage.user_id)
            .filter(Usage.user_id.isnot(None))
        )

        if start_date:
            query = query.filter(Usage.created_at >= start_date)
        if end_date:
            query = query.filter(Usage.created_at <= end_date)

        query = query.group_by(User.id, User.email, User.username)

        # 排序
        if order_by == "cost":
            query = query.order_by(func.sum(Usage.total_cost_usd).desc())
        elif order_by == "tokens":
            query = query.order_by(func.sum(Usage.total_tokens).desc())
        else:
            query = query.order_by(func.count(Usage.id).desc())

        results = query.limit(limit).all()

        return [
            {
                "user_id": row.id,
                "email": row.email,
                "username": row.username,
                "requests": row.requests,
                "tokens": row.tokens,
                "cost_usd": float(row.cost_usd),
            }
            for row in results
        ]

    @staticmethod
    def cleanup_old_usage_records(db: Session, days_to_keep: int = 90) -> int:
        """清理旧的使用记录"""

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)

        # 删除旧记录
        deleted = db.query(Usage).filter(Usage.created_at < cutoff_date).delete()

        db.commit()

        logger.info(f"清理使用记录: 删除 {deleted} 条超过 {days_to_keep} 天的记录")

        return deleted

    # ========== 请求状态追踪方法 ==========

    @classmethod
    def create_pending_usage(
        cls,
        db: Session,
        request_id: str,
        user: Optional[User],
        api_key: Optional[ApiKey],
        model: str,
        is_stream: bool = False,
        api_format: Optional[str] = None,
        request_headers: Optional[Dict[str, Any]] = None,
        request_body: Optional[Any] = None,
    ) -> Usage:
        """
        创建 pending 状态的使用记录（在请求开始时调用）

        Args:
            db: 数据库会话
            request_id: 请求ID
            user: 用户对象
            api_key: API Key 对象
            model: 模型名称
            is_stream: 是否流式请求
            api_format: API 格式
            request_headers: 请求头
            request_body: 请求体

        Returns:
            创建的 Usage 记录
        """
        # 根据配置决定是否记录请求详情
        should_log_headers = SystemConfigService.should_log_headers(db)
        should_log_body = SystemConfigService.should_log_body(db)

        # 处理请求头
        processed_request_headers = None
        if should_log_headers and request_headers:
            processed_request_headers = SystemConfigService.mask_sensitive_headers(
                db, request_headers
            )

        # 处理请求体
        processed_request_body = None
        if should_log_body and request_body:
            processed_request_body = SystemConfigService.truncate_body(
                db, request_body, is_request=True
            )

        usage = Usage(
            user_id=user.id if user else None,
            api_key_id=api_key.id if api_key else None,
            request_id=request_id,
            provider="pending",  # 尚未确定 provider
            model=model,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            total_cost_usd=0.0,
            request_type="chat",
            api_format=api_format,
            is_stream=is_stream,
            status="pending",
            request_headers=processed_request_headers,
            request_body=processed_request_body,
        )

        db.add(usage)
        db.commit()

        logger.debug(f"创建 pending 使用记录: request_id={request_id}, model={model}")

        return usage

    @classmethod
    def update_usage_status(
        cls,
        db: Session,
        request_id: str,
        status: str,
        error_message: Optional[str] = None,
    ) -> Optional[Usage]:
        """
        快速更新使用记录状态（不更新其他字段）

        Args:
            db: 数据库会话
            request_id: 请求ID
            status: 新状态 (pending, streaming, completed, failed)
            error_message: 错误消息（仅在 failed 状态时使用）

        Returns:
            更新后的 Usage 记录，如果未找到则返回 None
        """
        usage = db.query(Usage).filter(Usage.request_id == request_id).first()
        if not usage:
            logger.warning(f"未找到 request_id={request_id} 的使用记录，无法更新状态")
            return None

        old_status = usage.status
        usage.status = status
        if error_message:
            usage.error_message = error_message

        db.commit()

        logger.debug(f"更新使用记录状态: request_id={request_id}, {old_status} -> {status}")

        return usage

    @classmethod
    def get_active_requests(
        cls,
        db: Session,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Usage]:
        """
        获取活跃的请求（pending 或 streaming 状态）

        Args:
            db: 数据库会话
            user_id: 用户ID（可选，用于过滤）
            limit: 最大返回数量

        Returns:
            活跃请求的 Usage 列表
        """
        query = db.query(Usage).filter(Usage.status.in_(["pending", "streaming"]))

        if user_id:
            query = query.filter(Usage.user_id == user_id)

        return query.order_by(Usage.created_at.desc()).limit(limit).all()

    @classmethod
    def cleanup_stale_pending_requests(
        cls,
        db: Session,
        timeout_minutes: int = 10,
    ) -> int:
        """
        清理超时的 pending/streaming 请求

        将超过指定时间仍处于 pending 或 streaming 状态的请求标记为 failed。
        这些请求可能是由于网络问题、服务重启或其他异常导致未能正常完成。

        Args:
            db: 数据库会话
            timeout_minutes: 超时时间（分钟），默认 10 分钟

        Returns:
            清理的记录数
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        # 查找超时的请求
        stale_requests = (
            db.query(Usage)
            .filter(
                Usage.status.in_(["pending", "streaming"]),
                Usage.created_at < cutoff_time,
            )
            .all()
        )

        count = 0
        for usage in stale_requests:
            old_status = usage.status
            usage.status = "failed"
            usage.error_message = f"请求超时: 状态 '{old_status}' 超过 {timeout_minutes} 分钟未完成"
            usage.status_code = 504  # Gateway Timeout
            count += 1

        if count > 0:
            db.commit()
            logger.info(f"清理超时请求: 将 {count} 条超过 {timeout_minutes} 分钟的 pending/streaming 请求标记为 failed")

        return count

    @classmethod
    def get_stale_pending_count(
        cls,
        db: Session,
        timeout_minutes: int = 10,
    ) -> int:
        """
        获取超时的 pending/streaming 请求数量（用于监控）

        Args:
            db: 数据库会话
            timeout_minutes: 超时时间（分钟）

        Returns:
            超时请求数量
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        return (
            db.query(Usage)
            .filter(
                Usage.status.in_(["pending", "streaming"]),
                Usage.created_at < cutoff_time,
            )
            .count()
        )

    @classmethod
    def get_active_requests_status(
        cls,
        db: Session,
        ids: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        default_timeout_seconds: int = 300,
    ) -> List[Dict[str, Any]]:
        """
        获取活跃请求状态（用于前端轮询），并自动清理超时的 pending 请求

        与 get_active_requests 不同，此方法：
        1. 返回轻量级的状态字典而非完整 Usage 对象
        2. 自动检测并清理超时的 pending 请求
        3. 支持按 ID 列表查询特定请求

        Args:
            db: 数据库会话
            ids: 指定要查询的请求 ID 列表（可选）
            user_id: 限制只查询该用户的请求（可选，用于普通用户接口）
            default_timeout_seconds: 默认超时时间（秒），当端点未配置时使用

        Returns:
            请求状态列表
        """
        from src.models.database import ProviderEndpoint

        now = datetime.now(timezone.utc)

        # 构建基础查询，包含端点的 timeout 配置
        query = db.query(
            Usage.id,
            Usage.status,
            Usage.input_tokens,
            Usage.output_tokens,
            Usage.total_cost_usd,
            Usage.response_time_ms,
            Usage.created_at,
            Usage.provider_endpoint_id,
            ProviderEndpoint.timeout.label("endpoint_timeout"),
        ).outerjoin(ProviderEndpoint, Usage.provider_endpoint_id == ProviderEndpoint.id)

        if ids:
            query = query.filter(Usage.id.in_(ids))
            if user_id:
                query = query.filter(Usage.user_id == user_id)
        else:
            # 查询所有活跃请求
            query = query.filter(Usage.status.in_(["pending", "streaming"]))
            if user_id:
                query = query.filter(Usage.user_id == user_id)
            query = query.order_by(Usage.created_at.desc()).limit(50)

        records = query.all()

        # 检查超时的 pending 请求
        timeout_ids = []
        for r in records:
            if r.status == "pending" and r.created_at:
                # 使用端点配置的超时时间，若无则使用默认值
                timeout_seconds = r.endpoint_timeout or default_timeout_seconds

                # 处理时区：如果 created_at 没有时区信息，假定为 UTC
                created_at = r.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                elapsed = (now - created_at).total_seconds()
                if elapsed > timeout_seconds:
                    timeout_ids.append(r.id)

        # 批量更新超时的请求
        if timeout_ids:
            db.query(Usage).filter(Usage.id.in_(timeout_ids)).update(
                {"status": "failed", "error_message": "请求超时（服务器可能已重启）"},
                synchronize_session=False,
            )
            db.commit()

        return [
            {
                "id": r.id,
                "status": "failed" if r.id in timeout_ids else r.status,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost": float(r.total_cost_usd) if r.total_cost_usd else 0,
                "response_time_ms": r.response_time_ms,
            }
            for r in records
        ]

    # ========== 缓存亲和性分析方法 ==========

    @staticmethod
    def analyze_cache_affinity_ttl(
        db: Session,
        user_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        hours: int = 168,
    ) -> Dict[str, Any]:
        """
        分析用户请求间隔分布，推荐合适的缓存亲和性 TTL

        通过分析同一用户连续请求之间的时间间隔，判断用户的使用模式：
        - 高频用户（间隔短）：5 分钟 TTL 足够
        - 中频用户：15-30 分钟 TTL
        - 低频用户（间隔长）：需要 60 分钟 TTL

        Args:
            db: 数据库会话
            user_id: 指定用户 ID（可选，为空则分析所有用户）
            api_key_id: 指定 API Key ID（可选）
            hours: 分析最近多少小时的数据

        Returns:
            包含分析结果的字典
        """
        from sqlalchemy import text

        # 计算时间范围
        start_date = datetime.now(timezone.utc) - timedelta(hours=hours)

        # 构建 SQL 查询 - 使用窗口函数计算请求间隔
        # 按 user_id 或 api_key_id 分组，计算同一组内连续请求的时间差
        group_by_field = "api_key_id" if api_key_id else "user_id"

        # 构建过滤条件
        filter_clause = ""
        if user_id or api_key_id:
            filter_clause = f"AND {group_by_field} = :filter_id"

        sql = text(f"""
            WITH user_requests AS (
                SELECT
                    {group_by_field} as group_id,
                    created_at,
                    LAG(created_at) OVER (
                        PARTITION BY {group_by_field}
                        ORDER BY created_at
                    ) as prev_request_at
                FROM usage
                WHERE status = 'completed'
                  AND created_at > :start_date
                  AND {group_by_field} IS NOT NULL
                  {filter_clause}
            ),
            intervals AS (
                SELECT
                    group_id,
                    EXTRACT(EPOCH FROM (created_at - prev_request_at)) / 60.0 as interval_minutes
                FROM user_requests
                WHERE prev_request_at IS NOT NULL
            ),
            user_stats AS (
                SELECT
                    group_id,
                    COUNT(*) as request_count,
                    COUNT(*) FILTER (WHERE interval_minutes <= 5) as within_5min,
                    COUNT(*) FILTER (WHERE interval_minutes > 5 AND interval_minutes <= 15) as within_15min,
                    COUNT(*) FILTER (WHERE interval_minutes > 15 AND interval_minutes <= 30) as within_30min,
                    COUNT(*) FILTER (WHERE interval_minutes > 30 AND interval_minutes <= 60) as within_60min,
                    COUNT(*) FILTER (WHERE interval_minutes > 60) as over_60min,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY interval_minutes) as median_interval,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY interval_minutes) as p75_interval,
                    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY interval_minutes) as p90_interval,
                    AVG(interval_minutes) as avg_interval,
                    MIN(interval_minutes) as min_interval,
                    MAX(interval_minutes) as max_interval
                FROM intervals
                GROUP BY group_id
                HAVING COUNT(*) >= 2
            )
            SELECT * FROM user_stats
            ORDER BY request_count DESC
        """)

        params: Dict[str, Any] = {
            "start_date": start_date,
        }
        if user_id:
            params["filter_id"] = user_id
        elif api_key_id:
            params["filter_id"] = api_key_id

        result = db.execute(sql, params)
        rows = result.fetchall()

        # 收集所有 user_id 以便批量查询用户信息
        group_ids = [row[0] for row in rows]

        # 如果是按 user_id 分组，查询用户信息
        user_info_map: Dict[str, Dict[str, str]] = {}
        if group_by_field == "user_id" and group_ids:
            users = db.query(User).filter(User.id.in_(group_ids)).all()
            for user in users:
                user_info_map[str(user.id)] = {
                    "username": user.username,
                    "email": user.email or "",
                }

        # 处理结果
        users_analysis = []
        for row in rows:
            # row 是一个 tuple，按查询顺序访问
            (
                group_id,
                request_count,
                within_5min,
                within_15min,
                within_30min,
                within_60min,
                over_60min,
                median_interval,
                p75_interval,
                p90_interval,
                avg_interval,
                min_interval,
                max_interval,
            ) = row

            # 计算推荐 TTL
            recommended_ttl = UsageService._calculate_recommended_ttl(
                p75_interval, p90_interval
            )

            # 获取用户信息
            user_info = user_info_map.get(str(group_id), {})

            # 计算各区间占比
            total_intervals = request_count
            users_analysis.append({
                "group_id": group_id,
                "username": user_info.get("username"),
                "email": user_info.get("email"),
                "request_count": request_count,
                "interval_distribution": {
                    "within_5min": within_5min,
                    "within_15min": within_15min,
                    "within_30min": within_30min,
                    "within_60min": within_60min,
                    "over_60min": over_60min,
                },
                "interval_percentages": {
                    "within_5min": round(within_5min / total_intervals * 100, 1),
                    "within_15min": round(within_15min / total_intervals * 100, 1),
                    "within_30min": round(within_30min / total_intervals * 100, 1),
                    "within_60min": round(within_60min / total_intervals * 100, 1),
                    "over_60min": round(over_60min / total_intervals * 100, 1),
                },
                "percentiles": {
                    "p50": round(float(median_interval), 2) if median_interval else None,
                    "p75": round(float(p75_interval), 2) if p75_interval else None,
                    "p90": round(float(p90_interval), 2) if p90_interval else None,
                },
                "avg_interval_minutes": round(float(avg_interval), 2) if avg_interval else None,
                "min_interval_minutes": round(float(min_interval), 2) if min_interval else None,
                "max_interval_minutes": round(float(max_interval), 2) if max_interval else None,
                "recommended_ttl_minutes": recommended_ttl,
                "recommendation_reason": UsageService._get_ttl_recommendation_reason(
                    recommended_ttl, p75_interval, p90_interval
                ),
            })

        # 汇总统计
        ttl_distribution = {"5min": 0, "15min": 0, "30min": 0, "60min": 0}
        for analysis in users_analysis:
            ttl = analysis["recommended_ttl_minutes"]
            if ttl <= 5:
                ttl_distribution["5min"] += 1
            elif ttl <= 15:
                ttl_distribution["15min"] += 1
            elif ttl <= 30:
                ttl_distribution["30min"] += 1
            else:
                ttl_distribution["60min"] += 1

        return {
            "analysis_period_hours": hours,
            "total_users_analyzed": len(users_analysis),
            "ttl_distribution": ttl_distribution,
            "users": users_analysis,
        }

    @staticmethod
    def _calculate_recommended_ttl(
        p75_interval: Optional[float],
        p90_interval: Optional[float],
    ) -> int:
        """
        根据请求间隔分布计算推荐的缓存 TTL

        策略：
        - 如果 90% 的请求间隔都在 5 分钟内 → 5 分钟 TTL
        - 如果 75% 的请求间隔在 15 分钟内 → 15 分钟 TTL
        - 如果 75% 的请求间隔在 30 分钟内 → 30 分钟 TTL
        - 否则 → 60 分钟 TTL
        """
        if p90_interval is None or p75_interval is None:
            return 5  # 默认值

        # 如果 90% 的间隔都在 5 分钟内
        if p90_interval <= 5:
            return 5

        # 如果 75% 的间隔在 15 分钟内
        if p75_interval <= 15:
            return 15

        # 如果 75% 的间隔在 30 分钟内
        if p75_interval <= 30:
            return 30

        # 低频用户，需要更长的 TTL
        return 60

    @staticmethod
    def _get_ttl_recommendation_reason(
        ttl: int,
        p75_interval: Optional[float],
        p90_interval: Optional[float],
    ) -> str:
        """生成 TTL 推荐理由"""
        if p75_interval is None or p90_interval is None:
            return "数据不足，使用默认值"

        if ttl == 5:
            return f"高频用户：90% 的请求间隔在 {p90_interval:.1f} 分钟内"
        elif ttl == 15:
            return f"中高频用户：75% 的请求间隔在 {p75_interval:.1f} 分钟内"
        elif ttl == 30:
            return f"中频用户：75% 的请求间隔在 {p75_interval:.1f} 分钟内"
        else:
            return f"低频用户：75% 的请求间隔为 {p75_interval:.1f} 分钟，建议使用长 TTL"

    @staticmethod
    def get_cache_hit_analysis(
        db: Session,
        user_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        hours: int = 168,
    ) -> Dict[str, Any]:
        """
        分析缓存命中情况

        Args:
            db: 数据库会话
            user_id: 指定用户 ID（可选）
            api_key_id: 指定 API Key ID（可选）
            hours: 分析最近多少小时的数据

        Returns:
            缓存命中分析结果
        """
        start_date = datetime.now(timezone.utc) - timedelta(hours=hours)

        # 基础查询
        query = db.query(
            func.count(Usage.id).label("total_requests"),
            func.sum(Usage.input_tokens).label("total_input_tokens"),
            func.sum(Usage.cache_read_input_tokens).label("total_cache_read_tokens"),
            func.sum(Usage.cache_creation_input_tokens).label("total_cache_creation_tokens"),
            func.sum(Usage.cache_read_cost_usd).label("total_cache_read_cost"),
            func.sum(Usage.cache_creation_cost_usd).label("total_cache_creation_cost"),
        ).filter(
            Usage.status == "completed",
            Usage.created_at >= start_date,
        )

        if user_id:
            query = query.filter(Usage.user_id == user_id)
        if api_key_id:
            query = query.filter(Usage.api_key_id == api_key_id)

        result = query.first()

        total_requests = result.total_requests or 0
        total_input_tokens = result.total_input_tokens or 0
        total_cache_read_tokens = result.total_cache_read_tokens or 0
        total_cache_creation_tokens = result.total_cache_creation_tokens or 0
        total_cache_read_cost = float(result.total_cache_read_cost or 0)
        total_cache_creation_cost = float(result.total_cache_creation_cost or 0)

        # 计算缓存命中率（按 token 数）
        # 总输入上下文 = input_tokens + cache_read_tokens（因为 input_tokens 不含 cache_read）
        # 或者如果 input_tokens 已经包含 cache_read，则直接用 input_tokens
        # 这里假设 cache_read_tokens 是额外的，命中率 = cache_read / (input + cache_read)
        total_context_tokens = total_input_tokens + total_cache_read_tokens
        cache_hit_rate = 0.0
        if total_context_tokens > 0:
            cache_hit_rate = total_cache_read_tokens / total_context_tokens * 100

        # 计算节省的费用
        # 缓存读取价格是正常输入价格的 10%，所以节省了 90%
        # 节省 = cache_read_tokens * (正常价格 - 缓存价格) = cache_read_cost * 9
        # 因为 cache_read_cost 是按 10% 价格算的，如果按 100% 算就是 10 倍
        estimated_savings = total_cache_read_cost * 9  # 节省了 90%

        # 统计有缓存命中的请求数
        requests_with_cache_hit = db.query(func.count(Usage.id)).filter(
            Usage.status == "completed",
            Usage.created_at >= start_date,
            Usage.cache_read_input_tokens > 0,
        )
        if user_id:
            requests_with_cache_hit = requests_with_cache_hit.filter(Usage.user_id == user_id)
        if api_key_id:
            requests_with_cache_hit = requests_with_cache_hit.filter(Usage.api_key_id == api_key_id)
        requests_with_cache_hit = requests_with_cache_hit.scalar() or 0

        return {
            "analysis_period_hours": hours,
            "total_requests": total_requests,
            "requests_with_cache_hit": requests_with_cache_hit,
            "request_cache_hit_rate": round(requests_with_cache_hit / total_requests * 100, 2) if total_requests > 0 else 0,
            "total_input_tokens": total_input_tokens,
            "total_cache_read_tokens": total_cache_read_tokens,
            "total_cache_creation_tokens": total_cache_creation_tokens,
            "token_cache_hit_rate": round(cache_hit_rate, 2),
            "total_cache_read_cost_usd": round(total_cache_read_cost, 4),
            "total_cache_creation_cost_usd": round(total_cache_creation_cost, 4),
            "estimated_savings_usd": round(estimated_savings, 4),
        }

    @staticmethod
    def get_interval_timeline(
        db: Session,
        hours: int = 24,
        limit: int = 10000,
        user_id: Optional[str] = None,
        include_user_info: bool = False,
    ) -> Dict[str, Any]:
        """
        获取请求间隔时间线数据，用于散点图展示

        Args:
            db: 数据库会话
            hours: 分析最近多少小时的数据（默认24小时）
            limit: 最大返回数据点数量（默认10000）
            user_id: 指定用户 ID（可选，为空则返回所有用户）
            include_user_info: 是否包含用户信息（用于管理员多用户视图）

        Returns:
            包含时间线数据点的字典，每个数据点包含 model 字段用于按模型区分颜色
        """
        from sqlalchemy import text

        start_date = datetime.now(timezone.utc) - timedelta(hours=hours)

        # 构建用户过滤条件
        user_filter = "AND u.user_id = :user_id" if user_id else ""

        # 根据是否需要用户信息选择不同的查询
        if include_user_info and not user_id:
            # 管理员视图：返回带用户信息的数据点
            # 使用按比例采样，保持每个用户的数据量比例不变
            sql = text(f"""
                WITH request_intervals AS (
                    SELECT
                        u.created_at,
                        u.user_id,
                        u.model,
                        usr.username,
                        LAG(u.created_at) OVER (
                            PARTITION BY u.user_id
                            ORDER BY u.created_at
                        ) as prev_request_at
                    FROM usage u
                    LEFT JOIN users usr ON u.user_id = usr.id
                    WHERE u.status = 'completed'
                      AND u.created_at > :start_date
                      AND u.user_id IS NOT NULL
                      {user_filter}
                ),
                filtered_intervals AS (
                    SELECT
                        created_at,
                        user_id,
                        model,
                        username,
                        EXTRACT(EPOCH FROM (created_at - prev_request_at)) / 60.0 as interval_minutes,
                        ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at) as rn
                    FROM request_intervals
                    WHERE prev_request_at IS NOT NULL
                      AND EXTRACT(EPOCH FROM (created_at - prev_request_at)) / 60.0 <= 120
                ),
                total_count AS (
                    SELECT COUNT(*) as cnt FROM filtered_intervals
                ),
                user_totals AS (
                    SELECT user_id, COUNT(*) as user_cnt FROM filtered_intervals GROUP BY user_id
                ),
                user_limits AS (
                    SELECT
                        ut.user_id,
                        CASE WHEN tc.cnt <= :limit THEN ut.user_cnt
                             ELSE GREATEST(CEIL(ut.user_cnt::float * :limit / tc.cnt), 1)::int
                        END as user_limit
                    FROM user_totals ut, total_count tc
                )
                SELECT
                    fi.created_at,
                    fi.user_id,
                    fi.model,
                    fi.username,
                    fi.interval_minutes
                FROM filtered_intervals fi
                JOIN user_limits ul ON fi.user_id = ul.user_id
                WHERE fi.rn <= ul.user_limit
                ORDER BY fi.created_at
            """)
        else:
            # 普通视图：返回时间、间隔和模型信息
            sql = text(f"""
                WITH request_intervals AS (
                    SELECT
                        u.created_at,
                        u.user_id,
                        u.model,
                        LAG(u.created_at) OVER (
                            PARTITION BY u.user_id
                            ORDER BY u.created_at
                        ) as prev_request_at
                    FROM usage u
                    WHERE u.status = 'completed'
                      AND u.created_at > :start_date
                      AND u.user_id IS NOT NULL
                      {user_filter}
                )
                SELECT
                    created_at,
                    model,
                    EXTRACT(EPOCH FROM (created_at - prev_request_at)) / 60.0 as interval_minutes
                FROM request_intervals
                WHERE prev_request_at IS NOT NULL
                  AND EXTRACT(EPOCH FROM (created_at - prev_request_at)) / 60.0 <= 120
                ORDER BY created_at
                LIMIT :limit
            """)

        params: Dict[str, Any] = {"start_date": start_date, "limit": limit}
        if user_id:
            params["user_id"] = user_id

        result = db.execute(sql, params)
        rows = result.fetchall()

        # 转换为时间线数据点
        points = []
        users_map: Dict[str, str] = {}  # user_id -> username
        models_set: set = set()  # 收集所有出现的模型

        if include_user_info and not user_id:
            for row in rows:
                created_at, row_user_id, model, username, interval_minutes = row
                point_data: Dict[str, Any] = {
                    "x": created_at.isoformat(),
                    "y": round(float(interval_minutes), 2),
                    "user_id": str(row_user_id),
                }
                if model:
                    point_data["model"] = model
                    models_set.add(model)
                points.append(point_data)
                if row_user_id and username:
                    users_map[str(row_user_id)] = username
        else:
            for row in rows:
                created_at, model, interval_minutes = row
                point_data = {
                    "x": created_at.isoformat(),
                    "y": round(float(interval_minutes), 2)
                }
                if model:
                    point_data["model"] = model
                    models_set.add(model)
                points.append(point_data)

        response: Dict[str, Any] = {
            "analysis_period_hours": hours,
            "total_points": len(points),
            "points": points,
        }

        if include_user_info and not user_id:
            response["users"] = users_map

        # 如果有模型信息，返回模型列表
        if models_set:
            response["models"] = sorted(models_set)

        return response
