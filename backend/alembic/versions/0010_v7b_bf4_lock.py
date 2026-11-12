# -*- coding: utf-8 -*-
"""BF4-01：终端锁实例状态/心跳/释放失败持久化。"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_v7b_bf4_lock"
down_revision = "0009_v7b_bf3_close"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("device_write_lock") as batch:
        batch.add_column(sa.Column("state", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("release_state", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("release_error", sa.String(length=256), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("device_write_lock") as batch:
        batch.drop_column("release_error")
        batch.drop_column("release_state")
        batch.drop_column("last_seen_at")
        batch.drop_column("state")
