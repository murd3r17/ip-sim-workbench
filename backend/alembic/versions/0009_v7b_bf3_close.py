# -*- coding: utf-8 -*-
"""BF3：环境核验模式列；已应用 0008 的库再做一次安全 revision 修复。

Revision ID: 0009_v7b_bf3_close
Revises: 0008_v7b_bf2_compat
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_v7b_bf3_close"
down_revision = "0008_v7b_bf2_compat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("environment_profile") as batch:
        batch.add_column(sa.Column("last_preflight_mode", sa.String(length=16), nullable=True))

    # 已执行过 0008 的库：仅修 0 且 JSON 有合法 revision 的行；不清空有效内容/更高版本。
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        bind.execute(sa.text(
            "UPDATE training_session SET workspace_revision = "
            "CASE WHEN json_type(workspace, '$.revision') = 'integer' THEN MAX(json_extract(workspace, '$.revision'), 0) WHEN json_type(workspace, '$.revision') = 'text' AND json_extract(workspace, '$.revision') NOT GLOB '*[^0-9]*' THEN CAST(json_extract(workspace, '$.revision') AS INTEGER) ELSE 0 END "
            "WHERE workspace_revision = 0 AND workspace IS NOT NULL"
        ))
    elif dialect in {"mysql", "mariadb"}:
        bind.execute(sa.text(
            "UPDATE training_session SET workspace_revision = "
            "CASE WHEN JSON_TYPE(JSON_EXTRACT(workspace, '$.revision')) = 'INTEGER' THEN GREATEST(JSON_EXTRACT(workspace, '$.revision'), 0) WHEN JSON_TYPE(JSON_EXTRACT(workspace, '$.revision')) = 'STRING' AND JSON_UNQUOTE(JSON_EXTRACT(workspace, '$.revision')) REGEXP '^[0-9]+$' THEN CAST(JSON_UNQUOTE(JSON_EXTRACT(workspace, '$.revision')) AS SIGNED) ELSE 0 END "
            "WHERE workspace_revision = 0 AND workspace IS NOT NULL"
        ))


def downgrade() -> None:
    with op.batch_alter_table("environment_profile") as batch:
        batch.drop_column("last_preflight_mode")
