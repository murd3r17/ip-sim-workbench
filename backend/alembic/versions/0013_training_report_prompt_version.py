"""Allow complete training report prompt identities on MySQL."""

from alembic import op
import sqlalchemy as sa


revision = "0013_training_report_prompt"
down_revision = "0012_copilot_request"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("training_report") as batch:
        batch.alter_column("prompt_version", existing_type=sa.String(32), type_=sa.String(64),
                           existing_nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    length = "length" if bind.dialect.name == "sqlite" else "char_length"
    if bind.execute(sa.text(
        f"SELECT 1 FROM training_report WHERE {length}(prompt_version) > 32 LIMIT 1"
    )).first():
        raise RuntimeError("降级会截断已有报告版本标识，请先备份并处理这些报告")
    with op.batch_alter_table("training_report") as batch:
        batch.alter_column("prompt_version", existing_type=sa.String(64), type_=sa.String(32),
                           existing_nullable=True)
