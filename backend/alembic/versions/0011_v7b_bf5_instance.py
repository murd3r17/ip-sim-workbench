# -*- coding: utf-8 -*-
"""BF5：服务实例心跳/旧终端持有者身份。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_v7b_bf5_instance"
down_revision = "0010_v7b_bf4_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("device_write_lock") as batch:
        batch.add_column(sa.Column("owner_instance_id", sa.String(length=64), nullable=True))
    op.create_table(
        "service_instance",
        sa.Column("instance_id", sa.String(length=64), primary_key=True),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("process_started_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("service_instance")
    with op.batch_alter_table("device_write_lock") as batch:
        batch.drop_column("owner_instance_id")
