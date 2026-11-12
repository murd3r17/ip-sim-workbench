from pathlib import Path


def test_stage4_deploy_migration_is_idempotent_and_complete():
    migration = (
        Path(__file__).resolve().parents[3] / "init-sql" / "03-stage4-deploy.sql"
    ).read_text(encoding="utf-8").lower()

    assert "information_schema.columns" in migration
    for column in (
        "confirmed_by",
        "confirmed_at",
        "risk_confirmed_by",
        "risk_confirmed_at",
    ):
        assert f"column_name = '{column}'" in migration
        assert f"add column {column}" in migration
    assert "create table if not exists device_write_lock" in migration
    assert "foreign key (device_id) references device(id)" in migration
    assert "foreign key (task_id) references deploy_task(id)" in migration
