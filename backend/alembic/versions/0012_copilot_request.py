"""Durable assistant request identity and result recovery."""
from alembic import op
import sqlalchemy as sa

revision = "0012_copilot_request"
down_revision = "0011_v7b_bf5_instance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "copilot_request",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), primary_key=True),
        sa.Column("request_id", sa.String(64), primary_key=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("authorization_scope", sa.String(64), nullable=False),
        sa.Column("owner_token", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("copilot_request")
