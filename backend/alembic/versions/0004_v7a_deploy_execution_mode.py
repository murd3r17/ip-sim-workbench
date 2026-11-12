"""V7-A A-07: record the execution mode on each deploy task.

Historical tasks stay NULL ("mode not recorded") instead of being backfilled from
the current DEPLOY_SIMULATE_ONLY setting.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_v7a_deploy_execution_mode"
down_revision = "0003_v7a_training_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deploy_task") as batch:
        batch.add_column(sa.Column("execution_mode", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("deploy_task") as batch:
        batch.drop_column("execution_mode")
