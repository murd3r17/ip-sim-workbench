"""Store revocable browser sessions and shared login attempt windows."""

from alembic import op
import sqlalchemy as sa

revision = "0015_browser_sessions"
down_revision = "0014_terminal_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_instance", sa.Column("process_identity", sa.String(96), nullable=True))
    op.create_table(
        "browser_session",
        sa.Column("credential_digest", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_browser_session_user_id", "browser_session", ["user_id"])
    op.create_index("ix_browser_session_expires_at", "browser_session", ["expires_at"])
    op.create_table(
        "login_attempt_window",
        sa.Column("bucket", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )
    op.create_index("ix_login_attempt_window_expires_at", "login_attempt_window", ["expires_at"])


def downgrade() -> None:
    op.drop_table("login_attempt_window")
    op.drop_table("browser_session")
    op.drop_column("service_instance", "process_identity")
