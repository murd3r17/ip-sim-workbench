"""Delivery maintenance: revocation, optimistic saves and runtime provenance."""
from alembic import op
import sqlalchemy as sa

revision = "0002_delivery_maintenance"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("copilot_conversation", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("topology_runtime_check") as batch:
        batch.add_column(sa.Column("confirmed_version_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("baseline_fingerprint", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_runtime_check_confirmed_version", "topology_version", ["confirmed_version_id"], ["id"])
    # A former confirm operation overwrote version_id with its generated version.
    # Only that exact provenance proves a promotion; an old comparison is unknown.
    bind = op.get_bind()
    checks = sa.table("topology_runtime_check", sa.column("id"), sa.column("topology_id"),
                      sa.column("version_id"), sa.column("confirmed_version_id"))
    versions = sa.table("topology_version", sa.column("id"), sa.column("topology_id"),
                        sa.column("source_name"), sa.column("source_type"))
    rows = bind.execute(sa.select(checks.c.id, checks.c.version_id, versions.c.source_name).select_from(
        checks.join(versions, sa.and_(checks.c.version_id == versions.c.id,
                                     checks.c.topology_id == versions.c.topology_id))
    ).where(versions.c.source_type == "ensp")).all()
    for check_id, version_id, source_name in rows:
        if source_name == f"ensp-runtime-check-{check_id}":
            bind.execute(checks.update().where(checks.c.id == check_id).values(
                confirmed_version_id=version_id, version_id=None))


def downgrade() -> None:
    # Keep the generated baseline reference usable by the old application.
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE topology_runtime_check SET version_id=confirmed_version_id "
                         "WHERE version_id IS NULL AND confirmed_version_id IS NOT NULL"))
    with op.batch_alter_table("topology_runtime_check") as batch:
        batch.drop_constraint("fk_runtime_check_confirmed_version", type_="foreignkey")
        batch.drop_column("baseline_fingerprint")
        batch.drop_column("confirmed_version_id")
    op.drop_column("copilot_conversation", "revision")
    op.drop_column("user", "token_version")
