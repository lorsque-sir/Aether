"""add_indexes_for_model_alias_resolution

Revision ID: 6d0a5273f0f1
Revises: e9b3d63f0cbf
Create Date: 2025-12-15 09:50:23.423477+00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6d0a5273f0f1'
down_revision = 'e9b3d63f0cbf'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """应用迁移：升级到新版本"""
    # 为 Model 表添加索引，优化别名解析性能

    # 1. provider_model_name 索引（支持精确匹配）
    op.create_index(
        "idx_model_provider_model_name",
        "Model",
        ["provider_model_name"],
        unique=False,
        postgresql_where=sa.text("is_active = true"),
    )

    # 2. provider_model_aliases JSONB GIN 索引（支持 JSONB 查询，仅 PostgreSQL）
    # GIN 索引可以加速 @> 操作符的查询
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_model_provider_model_aliases_gin
        ON "Model" USING gin(provider_model_aliases)
        WHERE is_active = true
        """
    )


def downgrade() -> None:
    """回滚迁移：降级到旧版本"""
    # 删除索引
    op.drop_index("idx_model_provider_model_name", table_name="Model")
    op.execute('DROP INDEX IF EXISTS idx_model_provider_model_aliases_gin')
