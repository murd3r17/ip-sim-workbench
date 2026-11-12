# -*- coding: utf-8 -*-
"""BF2-03/04：旧 workspace revision 回填；终端锁实例令牌。

Revision ID: 0008_v7b_bf2_compat
Revises: 0007_v7b_bf_trust
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_v7b_bf2_compat"
down_revision = "0007_v7b_bf_trust"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    with op.batch_alter_table("device_write_lock") as batch:
        batch.add_column(sa.Column("owner_token", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("device_write_lock") as batch:
        batch.drop_column("owner_token")
