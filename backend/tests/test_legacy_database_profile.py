"""Known historical schema compatibility must not accept arbitrary drift."""
import enum

import pytest
import sqlalchemy as sa

from core.legacy_schema import legacy_metadata, repair_legacy_constraints
from core.legacy_types import LegacyReadableEnum
from core.migrations import _baseline_metadata, _schema_differences


class CurrentValue(str, enum.Enum):
    ACTIVE = "active"


def test_legacy_enum_reads_only_known_old_values_without_expanding_new_schema():
    metadata = sa.MetaData()
    table = sa.Table("historic", metadata, sa.Column("value", LegacyReadableEnum(CurrentValue, legacy_values=("retired",))))
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO historic VALUES ('active'), ('retired')"))
        values = connection.execute(sa.select(table.c.value)).scalars().all()
        assert values[0] is CurrentValue.ACTIVE
        assert values[1] == "retired"
        assert values[1].value == "retired"
        connection.execute(sa.text("INSERT INTO historic VALUES ('unrecognized')"))
        with pytest.raises(LookupError):
            connection.execute(sa.select(table.c.value)).all()
    assert table.c.value.type.impl.enums == ["active"]
    engine.dispose()


@pytest.mark.parametrize("table,column,value", [
    ("deploy_task", "status", "validating"),
    ("metric_record", "metric_type", "interface_in_bps"),
    ("metric_aggregated", "metric_type", "interface_out_bps"),
])
def test_mysql_model_decoder_preserves_historical_values(table, column, value):
    from sqlalchemy.dialects.mysql import pymysql
    from core.database import Base, _import_all_models

    _import_all_models()
    dialect = pymysql.dialect()
    declared = Base.metadata.tables[table].c[column].type
    adapted = declared.dialect_impl(dialect)
    decode = adapted.result_processor(dialect, None)
    assert decode(value).value == value
    assert value not in declared.impl.enums
    with pytest.raises(LookupError):
        decode("unexpected-historical-value")


def sqlite_profile(*, repaired=False):
    metadata = legacy_metadata(_baseline_metadata(), repaired=repaired)
    # MySQL's ON UPDATE timestamp suffix has no SQLite equivalent. This fixture
    # changes only that dialect syntax; all columns/constraints remain real.
    for table in metadata.tables.values():
        for column in table.columns:
            if column.server_default is not None and "ON UPDATE" in str(column.server_default.arg):
                column.server_default = sa.DefaultClause(sa.text("CURRENT_TIMESTAMP"))
    return metadata


def test_profile_is_a_copy_and_preserves_known_extras():
    baseline = _baseline_metadata()
    profile = legacy_metadata(baseline, repaired=False)
    assert "site" not in baseline.tables
    assert "retry_count" not in baseline.tables["deploy_task"].c
    assert {"site", "device_group"} <= set(profile.tables)
    assert profile.tables["deploy_task"].c.status.type.enums[3] == "validating"
    assert "interface_in_bps" in profile.tables["metric_record"].c.metric_type.type.enums
    assert profile.tables["device"].c.status.nullable
    assert not any(c.name == "uq_agg_device_metric_period" for c in profile.tables["metric_aggregated"].constraints)


@pytest.mark.parametrize("drift", ["unknown_table", "missing_unique", "wrong_default", "extra_column"])
def test_complete_profile_does_not_hide_unknown_drift(drift):
    metadata = sqlite_profile(repaired=True)
    engine = sa.create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as connection:
        assert _schema_differences(connection, metadata) == []
        if drift == "unknown_table":
            connection.execute(sa.text("CREATE TABLE unexpected (id INTEGER PRIMARY KEY)"))
        elif drift == "missing_unique":
            connection.execute(sa.text("DROP INDEX username"))
        elif drift == "wrong_default":
            metadata.tables["device"].c.ssh_port.server_default = sa.DefaultClause(sa.text("23"))
        else:
            connection.execute(sa.text("ALTER TABLE site ADD COLUMN surprise INTEGER"))
        assert _schema_differences(connection, metadata)
    engine.dispose()


def test_duplicate_aggregate_fails_before_repair_writes():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE metric_aggregated (device_id INT, metric_type TEXT, agg_level TEXT, period_start TEXT)"))
        connection.execute(sa.text("INSERT INTO metric_aggregated VALUES (1,'cpu_usage','hourly','2026-01-01'), (1,'cpu_usage','hourly','2026-01-01')"))
        connection.execute(sa.text("CREATE TABLE device (status TEXT)"))
        connection.execute(sa.text("INSERT INTO device VALUES (NULL)"))
        with pytest.raises(RuntimeError, match="重复"):
            repair_legacy_constraints(connection)
        assert connection.execute(sa.text("SELECT COUNT(*) FROM device WHERE status IS NULL")).scalar_one() == 1
        assert connection.execute(sa.text("SELECT COUNT(*) FROM metric_aggregated")).scalar_one() == 2
    engine.dispose()
