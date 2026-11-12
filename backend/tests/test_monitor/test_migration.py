from pathlib import Path


def test_stage5_monitor_job_migration_matches_runtime_model():
    migration = (
        Path(__file__).resolve().parents[3] / "init-sql" / "04-stage5-monitor.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table if not exists monitor_job" in migration
    for column in (
        "topology_id",
        "job_type",
        "trigger_mode",
        "status",
        "triggered_by",
        "summary_json",
        "report_json",
        "error_message",
        "started_at",
        "finished_at",
    ):
        assert column in migration
    for index in (
        "ix_monitor_job_topology",
        "ix_monitor_job_kind",
        "ix_monitor_job_status",
    ):
        assert index in migration
    assert "foreign key (topology_id) references topology(id)" in migration
    assert "foreign key (triggered_by) references user(id)" in migration
