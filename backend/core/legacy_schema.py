"""Exact schema profile for the pre-maintenance V6 MySQL installation.

This is an alternative full metadata definition, not an autogeneration ignore
list. Unknown tables, columns, defaults, enums and constraints still fail the
same strict comparison. Existing historical extras are retained, never dropped.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

PROFILE = "legacy_v6_mysql"

_DEFAULTS = {
    "audit_log": {"result": "'success'", "created_at": "CURRENT_TIMESTAMP"},
    "deploy_batch": {"source": "'manual'"},
    "device": {"ssh_port": "22", "vendor": "'huawei'", "status": "'unknown'", "network_role": "'access'",
               "created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
    "device_write_lock": {"lock_type": "'deploy'"},
    "monitor_job": {"status": "'pending'", "device_count": "0", "success_count": "0", "failure_count": "0",
                    "created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
    "topology": {"topology_type": "'main'", "device_count": "0", "status": "'active'",
                 "created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
    "topology_link": {"link_type": "'physical'", "status": "'up'", "source_type": "'baseline'",
                      "created_at": "CURRENT_TIMESTAMP", "updated_at": "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
    "topology_runtime_check": {"ssh_success": "0", "ssh_failed": "0", "created_at": "CURRENT_TIMESTAMP"},
    "topology_version": {"source_type": "'excel'", "created_at": "CURRENT_TIMESTAMP"},
    "user": {"role": "'user'", "is_active": "1", "created_at": "CURRENT_TIMESTAMP",
             "updated_at": "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"},
}
_DEPLOY_VALUES = ("pending", "awaiting_confirmation", "confirmed", "validating", "deploying",
                  "verifying", "success", "failed", "rolled_back", "cancelled")
_METRIC_VALUES = ("cpu_usage", "memory_usage", "interface_in_bps", "interface_out_bps", "interface_up",
                  "interface_down", "ospf_neighbor_count", "temperature")


def legacy_metadata(base, *, repaired, device_not_null=None, aggregate_unique=None):
    metadata = sa.MetaData()
    for table in base.tables.values():
        table.to_metadata(metadata)
    for name, defaults in _DEFAULTS.items():
        for column, value in defaults.items():
            metadata.tables[name].c[column].server_default = sa.DefaultClause(sa.text(value))
    sa.Table("site", metadata,
             sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
             sa.Column("name", sa.String(128), nullable=False), sa.Column("address", sa.String(256)),
             sa.Column("description", sa.Text), sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")))
    group = sa.Table("device_group", metadata,
                     sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
                     sa.Column("name", sa.String(128), nullable=False), sa.Column("description", sa.Text),
                     sa.Column("parent_id", sa.Integer, sa.ForeignKey("device_group.id")),
                     sa.Column("created_at", sa.DateTime, server_default=sa.text("CURRENT_TIMESTAMP")))
    sa.Index("parent_id", group.c.parent_id)
    task = metadata.tables["deploy_task"]
    task.append_column(sa.Column("retry_count", sa.Integer, nullable=True))
    task.c.status.type = sa.Enum(*_DEPLOY_VALUES, name="deploystatus")
    for name in ("metric_record", "metric_aggregated"):
        metadata.tables[name].c.metric_type.type = sa.Enum(*_METRIC_VALUES, name="metrictype")
    metadata.tables["device"].c.status.nullable = not (repaired if device_not_null is None else device_not_null)
    if not (repaired if aggregate_unique is None else aggregate_unique):
        table = metadata.tables["metric_aggregated"]
        table.constraints = {item for item in table.constraints if item.name != "uq_agg_device_metric_period"}
    for name, table, columns in (
        ("ix_audit_module", "audit_log", ("module",)),
        ("ix_audit_user_time", "audit_log", ("user_id", "created_at")),
        ("ix_topology_version_topology", "topology_version", ("topology_id", "version")),
    ):
        sa.Index(name, *(metadata.tables[table].c[column] for column in columns))
    user = metadata.tables["user"]
    user.indexes = {index for index in user.indexes if index.name != "ix_user_username"}
    sa.Index("ix_user_username", user.c.username)
    sa.Index("username", user.c.username, unique=True)
    return metadata


def matches_legacy_profile(connection, base, *, repaired):
    if connection.dialect.name != "mysql":
        return False
    from core.migrations import _schema_differences

    # MySQL DDL commits independently. Accept exactly the two repair checkpoints
    # on retry, with every other historical schema property still checked.
    checkpoints = [(True, True)] if repaired else [(False, False), (True, False), (False, True), (True, True)]
    return any(not _schema_differences(connection, legacy_metadata(
        base, repaired=repaired, device_not_null=not_null, aggregate_unique=unique,
    )) for not_null, unique in checkpoints)


def repair_legacy_constraints(connection):
    """Preserve rows; never deduplicate aggregates by deleting or merging them."""
    duplicates = connection.execute(sa.text(
        "SELECT COUNT(*) FROM (SELECT device_id,metric_type,agg_level,period_start "
        "FROM metric_aggregated GROUP BY device_id,metric_type,agg_level,period_start HAVING COUNT(*)>1) duplicates"
    )).scalar_one()
    if duplicates:
        raise RuntimeError("历史聚合数据存在重复周期，拒绝修改；请人工核对重复数据并保留备份")
    null_count = connection.execute(sa.text("SELECT COUNT(*) FROM device WHERE status IS NULL")).scalar_one()
    inspector = sa.inspect(connection)
    operations = Operations(MigrationContext.configure(connection))
    status = next(column for column in inspector.get_columns("device") if column["name"] == "status")
    if status["nullable"]:
        if null_count:
            connection.execute(sa.text("UPDATE device SET status='unknown' WHERE status IS NULL"))
        operations.alter_column("device", "status", nullable=False, existing_type=status["type"],
                                existing_server_default=sa.text("'unknown'"))
    if not any(item["name"] == "uq_agg_device_metric_period" for item in inspector.get_unique_constraints("metric_aggregated")):
        operations.create_unique_constraint("uq_agg_device_metric_period", "metric_aggregated",
                                             ["device_id", "metric_type", "agg_level", "period_start"])
    return {"profile": PROFILE, "device_null_status_backfilled": null_count, "aggregate_duplicate_groups": duplicates}
