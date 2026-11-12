"""V7-B B-07/08/10: versioned environments, read-only evidence, training workspace."""
from alembic import op
import sqlalchemy as sa

revision = "0006_v7b_trust_base"
down_revision = "0005_v7a_session_mode_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environment_profile",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("site", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("devices", sa.JSON(), nullable=True),
        sa.Column("protections", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_environment_status", "environment_profile", ["status"])
    op.create_table(
        "read_only_observation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment_profile.id"), nullable=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("device.id"), nullable=False),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("completeness", sa.String(length=16), nullable=False),
        sa.Column("parser_version", sa.String(length=32), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=True),
        sa.Column("raw_excerpt", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_observation_device_time", "read_only_observation", ["device_id", "collected_at"])
    op.create_index("ix_observation_environment", "read_only_observation", ["environment_id"])
    with op.batch_alter_table("training_session") as batch:
        batch.add_column(sa.Column("workspace", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("training_session") as batch:
        batch.drop_column("workspace")
    op.drop_index("ix_observation_environment", table_name="read_only_observation")
    op.drop_index("ix_observation_device_time", table_name="read_only_observation")
    op.drop_table("read_only_observation")
    op.drop_index("ix_environment_status", table_name="environment_profile")
    op.drop_table("environment_profile")
