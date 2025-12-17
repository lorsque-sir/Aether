"""
审计日志服务
记录所有重要操作和安全事件
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.core.logger import logger
from src.database import get_db
from src.models.database import AuditEventType, AuditLog



# 审计模型已移至 src/models/database.py


class AuditService:
    """审计服务

    事务策略：本服务不负责事务提交，由中间件统一管理。
    所有方法只做 db.add/flush，提交由请求结束时的中间件处理。
    """

    @staticmethod
    def log_event(
        db: Session,
        event_type: AuditEventType,
        description: str,
        user_id: Optional[str] = None,  # UUID
        api_key_id: Optional[str] = None,  # UUID
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """
        记录审计事件

        Args:
            db: 数据库会话
            event_type: 事件类型
            description: 事件描述
            user_id: 用户ID
            api_key_id: API密钥ID
            ip_address: IP地址
            user_agent: 用户代理
            request_id: 请求ID
            status_code: 状态码
            error_message: 错误消息
            metadata: 额外元数据

        Returns:
            审计日志记录

        Note:
            不在此方法内提交事务，由调用方或中间件统一管理。
        """
        audit_log = AuditLog(
            event_type=event_type.value,
            description=description,
            user_id=user_id,
            api_key_id=api_key_id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            status_code=status_code,
            error_message=error_message,
            event_metadata=metadata,
        )

        db.add(audit_log)
        # 使用 flush 使记录可见但不提交事务，事务由中间件统一管理
        db.flush()

        # 同时记录到系统日志
        log_message = (
            f"AUDIT [{event_type.value}] - {description} | "
            f"user_id={user_id}, ip={ip_address}"
        )

        if event_type in [
            AuditEventType.UNAUTHORIZED_ACCESS,
            AuditEventType.SUSPICIOUS_ACTIVITY,
        ]:
            logger.warning(log_message)
        elif event_type in [AuditEventType.LOGIN_FAILED, AuditEventType.REQUEST_FAILED]:
            logger.info(log_message)
        else:
            logger.debug(log_message)

        return audit_log

    @staticmethod
    def log_login_attempt(
        db: Session,
        email: str,
        success: bool,
        ip_address: str,
        user_agent: str,
        user_id: Optional[str] = None,  # UUID
        error_reason: Optional[str] = None,
    ):
        """
        记录登录尝试

        Args:
            db: 数据库会话
            email: 登录邮箱
            success: 是否成功
            ip_address: IP地址
            user_agent: 用户代理
            user_id: 用户ID（成功时）
            error_reason: 失败原因
        """
        event_type = AuditEventType.LOGIN_SUCCESS if success else AuditEventType.LOGIN_FAILED
        description = f"Login attempt for {email}"
        if not success and error_reason:
            description += f": {error_reason}"

        AuditService.log_event(
            db=db,
            event_type=event_type,
            description=description,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={"email": email},
        )

    @staticmethod
    def log_api_request(
        db: Session,
        user_id: str,  # UUID
        api_key_id: str,  # UUID
        request_id: str,
        model: str,
        provider: str,
        success: bool,
        ip_address: str,
        status_code: int,
        error_message: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
    ):
        """
        记录API请求

        Args:
            db: 数据库会话
            user_id: 用户ID
            api_key_id: API密钥ID
            request_id: 请求ID
            model: 模型名称
            provider: 提供商名称
            success: 是否成功
            ip_address: IP地址
            status_code: 状态码
            error_message: 错误消息
            input_tokens: 输入tokens
            output_tokens: 输出tokens
            cost_usd: 成本（美元）
        """
        event_type = AuditEventType.REQUEST_SUCCESS if success else AuditEventType.REQUEST_FAILED
        description = f"API request to {provider}/{model}"

        metadata = {"model": model, "provider": provider}

        if input_tokens:
            metadata["input_tokens"] = input_tokens
        if output_tokens:
            metadata["output_tokens"] = output_tokens
        if cost_usd:
            metadata["cost_usd"] = cost_usd

        AuditService.log_event(
            db=db,
            event_type=event_type,
            description=description,
            user_id=user_id,
            api_key_id=api_key_id,
            request_id=request_id,
            ip_address=ip_address,
            status_code=status_code,
            error_message=error_message,
            metadata=metadata,
        )

    @staticmethod
    def log_security_event(
        db: Session,
        event_type: AuditEventType,
        description: str,
        ip_address: str,
        user_id: Optional[str] = None,  # UUID
        severity: str = "medium",
        details: Optional[Dict[str, Any]] = None,
    ):
        """
        记录安全事件

        Args:
            db: 数据库会话
            event_type: 事件类型
            description: 事件描述
            ip_address: IP地址
            user_id: 用户ID
            severity: 严重程度 (low, medium, high, critical)
            details: 详细信息
        """
        event_metadata = {"severity": severity}
        if details:
            event_metadata.update(details)

        AuditService.log_event(
            db=db,
            event_type=event_type,
            description=description,
            user_id=user_id,
            ip_address=ip_address,
            metadata=event_metadata,
        )

        # 对于高严重性事件，简化日志输出
        if severity in ["high", "critical"]:
            logger.error(f"安全告警 [{severity.upper()}]: {description}")

    @staticmethod
    def get_user_audit_logs(
        db: Session,
        user_id: str,  # UUID
        event_types: Optional[List[AuditEventType]] = None,
        limit: int = 100,
    ) -> List[AuditLog]:
        """
        获取用户的审计日志

        Args:
            db: 数据库会话
            user_id: 用户ID
            event_types: 事件类型过滤
            limit: 返回数量限制

        Returns:
            审计日志列表
        """
        query = db.query(AuditLog).filter(AuditLog.user_id == user_id)

        if event_types:
            event_type_values = [et.value for et in event_types]
            query = query.filter(AuditLog.event_type.in_(event_type_values))

        return query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_suspicious_activities(db: Session, hours: int = 24, limit: int = 100) -> List[AuditLog]:
        """
        获取可疑活动

        Args:
            db: 数据库会话
            hours: 时间范围（小时）
            limit: 返回数量限制

        Returns:
            可疑活动列表
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        suspicious_types = [
            AuditEventType.SUSPICIOUS_ACTIVITY.value,
            AuditEventType.UNAUTHORIZED_ACCESS.value,
            AuditEventType.LOGIN_FAILED.value,
            AuditEventType.REQUEST_RATE_LIMITED.value,
        ]

        return (
            db.query(AuditLog)
            .filter(AuditLog.event_type.in_(suspicious_types), AuditLog.created_at >= cutoff_time)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def analyze_user_behavior(db: Session, user_id: str, days: int = 30) -> Dict[str, Any]:  # UUID
        """
        分析用户行为

        Args:
            db: 数据库会话
            user_id: 用户ID
            days: 分析天数

        Returns:
            行为分析结果
        """
        from sqlalchemy import func

        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)

        # 统计各种事件类型
        event_counts = (
            db.query(AuditLog.event_type, func.count(AuditLog.id).label("count"))
            .filter(AuditLog.user_id == user_id, AuditLog.created_at >= cutoff_time)
            .group_by(AuditLog.event_type)
            .all()
        )

        # 统计失败请求
        failed_requests = (
            db.query(func.count(AuditLog.id))
            .filter(
                AuditLog.user_id == user_id,
                AuditLog.event_type == AuditEventType.REQUEST_FAILED.value,
                AuditLog.created_at >= cutoff_time,
            )
            .scalar()
        )

        # 统计成功请求
        success_requests = (
            db.query(func.count(AuditLog.id))
            .filter(
                AuditLog.user_id == user_id,
                AuditLog.event_type == AuditEventType.REQUEST_SUCCESS.value,
                AuditLog.created_at >= cutoff_time,
            )
            .scalar()
        )

        # 获取最近的可疑活动
        recent_suspicious = (
            db.query(AuditLog)
            .filter(
                AuditLog.user_id == user_id,
                AuditLog.event_type.in_(
                    [
                        AuditEventType.SUSPICIOUS_ACTIVITY.value,
                        AuditEventType.UNAUTHORIZED_ACCESS.value,
                    ]
                ),
                AuditLog.created_at >= cutoff_time,
            )
            .count()
        )

        return {
            "user_id": user_id,
            "period_days": days,
            "event_counts": {event: count for event, count in event_counts},
            "failed_requests": failed_requests or 0,
            "success_requests": success_requests or 0,
            "success_rate": (
                success_requests / (success_requests + failed_requests)
                if (success_requests + failed_requests) > 0
                else 0
            ),
            "suspicious_activities": recent_suspicious,
            "analysis_time": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def log_event_auto(
        event_type: AuditEventType,
        description: str,
        user_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
        event_metadata: Optional[Dict[str, Any]] = None,
        db: Optional[Session] = None,
    ) -> Optional[AuditLog]:
        """
        自动管理数据库会话的审计日志记录方法
        适用于中间件等无法直接获取数据库会话的场景

        Args:
            event_type: 事件类型
            description: 事件描述
            user_id: 用户ID
            api_key_id: API密钥ID
            ip_address: IP地址
            user_agent: 用户代理
            request_id: 请求ID
            status_code: 状态码
            error_message: 错误消息
            event_metadata: 额外元数据
            db: 数据库会话（可选，如不提供则自动创建）

        Returns:
            审计日志记录
        """
        # 如果提供了数据库会话，使用它（不自动提交）
        if db is not None:
            try:
                audit_log = AuditService.log_event(
                    db=db,
                    event_type=event_type,
                    description=description,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    request_id=request_id,
                    status_code=status_code,
                    error_message=error_message,
                    metadata=event_metadata,
                )
                # 注意：不在这里提交，让调用方决定何时提交
                return audit_log

            except Exception as e:
                logger.error(f"Failed to log audit event: {e}")
                return None

        # 如果没有提供会话，自动创建并管理
        db_session = None
        try:
            db_session = next(get_db())

            audit_log = AuditService.log_event(
                db=db_session,
                event_type=event_type,
                description=description,
                user_id=user_id,
                api_key_id=api_key_id,
                ip_address=ip_address,
                user_agent=user_agent,
                request_id=request_id,
                status_code=status_code,
                error_message=error_message,
                metadata=event_metadata,
            )

            db_session.commit()
            return audit_log

        except Exception as e:
            logger.error(f"Failed to log audit event with auto session: {e}")
            if db_session is not None:
                db_session.rollback()
            return None
        finally:
            if db_session is not None:
                db_session.close()


# 全局审计服务实例
audit_service = AuditService()
