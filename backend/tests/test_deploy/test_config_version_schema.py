from modules.deploy.schemas import ConfigVersionResponse


def test_config_version_response_exposes_task_link_and_source():
    response = ConfigVersionResponse(
        id=7,
        device_id=3,
        version_number=2,
        config_snapshot="display current-configuration",
        change_description="post change",
        created_at="2026-08-04T10:00:00",
        source="post_readback",
        deploy_task_id=42,
    )

    assert response.model_dump()["deploy_task_id"] == 42
    assert response.model_dump()["source"] == "post_readback"
