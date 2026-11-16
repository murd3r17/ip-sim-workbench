"""Add administrator-issued device terminal permissions."""

from alembic import op
import sqlalchemy as sa

revision = "0014_terminal_grants"
down_revision = "0013_training_report_prompt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "terminal_grant",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("device_id", sa.Integer(), sa.ForeignKey("device.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("grant_id", sa.String(32), nullable=False),
        sa.Column("management_address", sa.String(64), nullable=False),
        sa.Column("ssh_port", sa.Integer(), nullable=False),
        sa.Column("issued_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(240), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("terminal_grant")
