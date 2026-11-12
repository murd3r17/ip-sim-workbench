# -*- coding: utf-8 -*-
"""BF-01/02/03/04：环境快照、证据来源/版本、共享占用、workspace CAS。

Revision ID: 0007_v7b_bf_trust
Revises: 0006_v7b_trust_base
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_v7b_bf_trust"
down_revision = "0006_v7b_trust_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("environment_profile") as batch:
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("content_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("expected", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("last_preflight_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("last_preflight_at", sa.DateTime(), nullable=True))
    with op.batch_alter_table("environment_profile") as batch:
        batch.alter_column("revision", server_default=None)

    with op.batch_alter_table("read_only_observation") as batch:
        batch.add_column(sa.Column("environment_version", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("environment_snapshot", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("adapter_mode", sa.String(length=16), nullable=False, server_default="unknown"))
    with op.batch_alter_table("read_only_observation") as batch:
        batch.alter_column("adapter_mode", server_default=None)

    op.add_column("training_session", sa.Column("workspace_revision", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("training_session") as batch:
        batch.add_column(sa.Column("trust_environment_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("trust_environment_version", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("trust_environment_snapshot", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_training_session_trust_environment", "environment_profile",
            ["trust_environment_id"], ["id"],
        )
    with op.batch_alter_table("training_session") as batch:
        batch.alter_column("workspace_revision", server_default=None)

    # BF-03：终端/训练写路径与部署共用同一把 device_write_lock。
    with op.batch_alter_table("device_write_lock") as batch:
        batch.alter_column("task_id", existing_type=sa.Integer(), nullable=True)
        batch.add_column(sa.Column("owner_type", sa.String(length=16), nullable=False, server_default="deploy"))
        batch.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
    with op.batch_alter_table("device_write_lock") as batch:
        batch.alter_column("owner_type", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("device_write_lock") as batch:
        batch.drop_column("owner_id")
        batch.drop_column("owner_type")
    with op.batch_alter_table("device_write_lock") as batch:
        batch.alter_column("task_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("training_session") as batch:
        batch.drop_constraint("fk_training_session_trust_environment", type_="foreignkey")
        batch.drop_column("trust_environment_snapshot")
        batch.drop_column("trust_environment_version")
        batch.drop_column("trust_environment_id")
        batch.drop_column("workspace_revision")
    with op.batch_alter_table("read_only_observation") as batch:
        batch.drop_column("adapter_mode")
        batch.drop_column("environment_snapshot")
        batch.drop_column("environment_version")
    with op.batch_alter_table("environment_profile") as batch:
        batch.drop_column("last_preflight_at")
        batch.drop_column("last_preflight_status")
        batch.drop_column("expected")
        batch.drop_column("content_hash")
        batch.drop_column("revision")
