"""Regressions from the novice walkthrough, using the existing HTTP fixture."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from modules.auth.models import User
from modules.device.models import Topology, TopologyType
from modules.training.models import LabStatus, TrainingLab, TrainingSession, TrainingReport
from modules.training.environment_policy import requests_site_configuration
from modules.training.reports import build_report_row, PROMPT_VERSION
from modules.training.service import TrainingService
from modules.training.step_verification import evaluate_frozen_step
from tests.test_c3_request_api import api_case, events


async def create_lab(factory, *, requires_binding=True):
    async with factory() as db:
        owner = (await db.execute(select(User).where(User.username == "report_admin"))).scalar_one_or_none()
        if owner is None:
            owner = (await db.execute(select(User).order_by(User.id))).scalars().first()
        topology = Topology(name=f"learning-{uuid.uuid4().hex}", topology_type=TopologyType.LAB)
        db.add(topology)
        await db.flush()
        lab = TrainingLab(
            title="互联与环回地址核对", topology_id=topology.id, instructor_id=owner.id,
            status=LabStatus.READY, environment_spec={"requires_binding": requires_binding},
            objectives=[{"id": 1, "name": "核对互联口", "goal": "区分互联口与环回口"}],
        )
        db.add(lab)
        await db.flush()
        session = TrainingSession(
            lab_id=lab.id, trainee_id=owner.id, status="in_progress",
            content_snapshot={"objectives": lab.objectives, "title": lab.title,
                              "environment_spec": lab.environment_spec},
        )
        db.add(session)
        await db.commit()
        return owner.id, lab.id, session.id


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
async def test_explaining_a_step_in_an_unbound_lab_reaches_the_model(api_case, test_session_factory, path):
    client, headers, provider, _ = api_case
    _, lab_id, session_id = await create_lab(test_session_factory)
    response = await client.post("/api/v1/ai/copilot" + path, headers=headers, json={
        "message": "这一步要看什么，怎么判断，记录什么证据？",
        "lab_id": lab_id, "lab_session_id": session_id, "request_id": uuid.uuid4().hex,
    })
    assert response.status_code == 200
    result = events(response)[-1] if path.endswith("stream") else response.json()
    assert result["status"] != "blocked_environment"
    assert provider.calls >= 1

    count = provider.calls
    blocked = await client.post("/api/v1/ai/copilot" + path, headers=headers, json={
        "message": "生成当前设备的可执行配置草稿", "want_draft": True,
        "lab_id": lab_id, "lab_session_id": session_id, "request_id": uuid.uuid4().hex,
    })
    result = events(blocked)[-1] if path.endswith("stream") else blocked.json()
    assert result["status"] == "blocked_environment"
    assert provider.calls == count


@pytest.mark.asyncio
async def test_followup_reads_the_saved_attachment_not_the_previous_answer(api_case, monkeypatch):
    client, headers, provider, retrieval = api_case
    prompts = []

    async def answer(prompt, system=None):
        prompts.append(prompt)
        yield {"kind": "content", "text": "本表中 GE1/0/2 为 up/down。"}

    monkeypatch.setattr(provider, "stream_parts", answer)
    conv_id = uuid.uuid4().hex
    saved = await client.put(f"/api/v1/ai/copilot/sessions/{conv_id}", headers=headers, json={
        "title": "观察文件",
        "messages": [{"id": "upload", "role": "user", "content": "有几条接口？",
                      "attachments": [{"name": "interfaces.txt", "mime": "text/plain",
                                       "contentString": "GE1/0/2 203.0.113.6/30 up down"}]}],
    })
    assert saved.status_code == 200
    response = await client.post("/api/v1/ai/copilot/chat/stream", headers=headers, json={
        "message": "GE1/0/2 的地址、物理和协议状态分别是什么？",
        "request_id": uuid.uuid4().hex, "conversation_id": conv_id, "attachment_message_id": "upload",
        "history": [{"role": "assistant", "content": "共四条接口。"}],
    })
    assert response.status_code == 200
    assert any("GE1/0/2 203.0.113.6/30 up down" in prompt and "interfaces.txt" in prompt for prompt in prompts)
    assert not retrieval.await_count


@pytest.mark.asyncio
async def test_new_legacy_course_attempt_has_its_own_version_and_manual_check(api_case, test_session_factory):
    user_id, lab_id, old_session_id = await create_lab(test_session_factory)
    async with test_session_factory() as db:
        session = await TrainingService.start_session(db, lab_id, user_id)
        check = evaluate_frozen_step(session, 1, [], [], {}, {"user_id": user_id})
        assert check["status"] == "manual_review"
        assert session.content_snapshot["version"] == session.content_version
        assert session.content_version
        old = await db.get(TrainingSession, old_session_id)
        assert old.content_version is None
        assert "version" not in old.content_snapshot


def test_saved_success_and_failure_use_a_version_that_fits_mysql():
    from core.database import _import_all_models
    _import_all_models()
    for status in ("ready", "failed"):
        row = build_report_row(1, 1, status=status, payload={}, input_hash="sample", summary={}, model=None)
        assert row.prompt_version == PROMPT_VERSION
        assert len(row.prompt_version) <= TrainingReport.__table__.c.prompt_version.type.length


@pytest.mark.parametrize(("question", "site_config"), [
    ("写一份当前设备的配置草稿，不执行。", True),
    ("给我现场可直接下发的配置，不要真的下发。", True),
    ("先给我这台设备能直接用的配置草稿，执行我之后自己确认。", True),
    ("只解释现场配置里的 area，别生成命令。", False),
    ("给我一个教材配置例子，说明怎样核对。", False),
    ("给我在现场用来只读核对邻居的 display 命令。", False),
])
def test_site_config_intent_is_separate_from_permission_to_execute(question, site_config):
    assert requests_site_configuration(question) is site_config


def complete_local_coroutine(awaitable):
    try:
        with pytest.raises(StopIteration) as result:
            awaitable.send(None)
        return result.value.value
    finally:
        awaitable.close()


def test_active_unbound_lab_explanation_does_not_expose_another_learners_steps():
    from modules.ai_text.router import _lab_draft_policy
    from modules.ai_text.schemas import CopilotChatRequest

    objectives = [{"id": 1, "name": "核对互联接口"}, {"id": 2, "name": "记录邻居状态"}]
    spec = {"requires_binding": True, "binding_status": "unverified"}
    lab = SimpleNamespace(id=7, title="接口和邻居", objectives=objectives, environment_spec=spec, content_version="v7ux.example")
    session = SimpleNamespace(id=14, lab_id=7, trainee_id=3, status="in_progress", content_version="v7ux.example",
        content_snapshot={"version": "v7ux.example", "title": lab.title, "objectives": objectives, "environment_spec": spec},
        workspace={"steps": [{"id": 1, "status": "done"}]})

    class Store:
        async def get(self, model, key):
            return {(TrainingSession, 14): session, (TrainingLab, 7): lab}.get((model, key))

    actor = {"user_id": 3, "role": "user"}
    explanation = CopilotChatRequest(message="这一步要观察什么？", lab_session_id=14)
    policy = complete_local_coroutine(_lab_draft_policy(Store(), explanation, actor))
    assert policy["allow_model"] is True and policy["allow_draft"] is False
    assert policy["lab_content"]["first_unmarked_step_id"] == 2

    draft = explanation.model_copy(update={"message": "给我当前设备的可下发配置草稿，不执行。"})
    policy = complete_local_coroutine(_lab_draft_policy(Store(), draft, actor))
    assert policy["allow_model"] is False and policy["allow_draft"] is False

    denied = complete_local_coroutine(_lab_draft_policy(Store(), explanation, {**actor, "user_id": 4}))
    assert denied["allow_model"] is False
    assert "lab_steps" not in denied


def test_empty_inspection_explanation_never_requests_a_model(monkeypatch):
    from modules.ai_text import router
    from modules.ai_text.schemas import InspectionSummaryRequest

    async def unavailable(*args):
        pytest.fail("No model request can substantiate zero observations")

    monkeypatch.setattr(router, "_get_service", unavailable)

    class Store:
        async def get(self, model, key):
            return SimpleNamespace(id=key, status="completed", device_count=3, success_count=0, failure_count=1,
                finished_at=None, summary_json='{"skipped": 2, "errors": ["R2 管理连接超时"]}', report_json=None)

    result = complete_local_coroutine(router.inspection_summary(InspectionSummaryRequest(job_id=17), Store(), {"user_id": 3}))
    assert result["basis"] == "no_current_observations"
    assert result["coverage"] == {"target": 3, "observed": 0, "failed": 1, "skipped": 2, "finished_at": None}
    assert "健康情况未知" in result["summary"]
    assert not result["root_causes"]


def test_batch_summary_distinguishes_cancellation_rollback_and_execution_failure():
    from modules.deploy.models import DeployStatus
    from modules.deploy.router import _batch_summary

    tasks = [SimpleNamespace(status=status) for status in (
        DeployStatus.CONFIRMED, DeployStatus.CANCELLED, DeployStatus.ROLLED_BACK, DeployStatus.FAILED, DeployStatus.VERIFYING,
    )]
    assert _batch_summary(tasks) == {
        "total": 5, "pending": 0, "waiting": 1, "running": 1, "success": 0,
        "failed": 3, "execution_failed": 1, "cancelled": 1, "rolled_back": 1,
    }
