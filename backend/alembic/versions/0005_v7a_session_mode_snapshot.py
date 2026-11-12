"""V7-A A-fix AF-04: snapshot device/deploy/binding facts at session start.

Existing sessions keep NULL and are reported as unknown history instead of being
backfilled from the current settings.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_v7a_session_mode_snapshot"
down_revision = "0004_v7a_deploy_execution_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("training_session") as batch:
        batch.add_column(sa.Column("mode_snapshot", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("training_session") as batch:
        batch.drop_column("mode_snapshot")
