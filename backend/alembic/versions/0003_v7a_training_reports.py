"""V7-A: lab content version/binding hints, session content snapshot, persisted reports.

Adds only nullable columns and one new table; existing rows keep their data and are
not rewritten. Historical sessions without ``content_snapshot`` stay readable and
are labelled as having no versioned evidence by the API instead of being backfilled.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_v7a_training_reports"
down_revision = "0002_delivery_maintenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("training_lab") as batch:
        batch.add_column(sa.Column("content_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("environment_spec", sa.JSON(), nullable=True))
    with op.batch_alter_table("training_session") as batch:
        batch.add_column(sa.Column("content_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("content_snapshot", sa.JSON(), nullable=True))
    op.create_table(
        "training_report",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("training_session.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("key_findings", sa.JSON(), nullable=True),
        sa.Column("root_causes", sa.JSON(), nullable=True),
        sa.Column("impact_analysis", sa.JSON(), nullable=True),
        sa.Column("recommendations", sa.JSON(), nullable=True),
        sa.Column("report_text", sa.Text(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("input_summary", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("session_id", "version", name="uq_training_report_session_version"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_training_report_idempotency"),
    )
    op.create_index("ix_training_report_session", "training_report", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_training_report_session", table_name="training_report")
    op.drop_table("training_report")
    with op.batch_alter_table("training_session") as batch:
        batch.drop_column("content_snapshot")
        batch.drop_column("content_version")
    with op.batch_alter_table("training_lab") as batch:
        batch.drop_column("environment_spec")
        batch.drop_column("content_version")
