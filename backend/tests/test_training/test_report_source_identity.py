"""Persist exactly the report excerpts sent to the model; failures are not empty retrieval."""
import hashlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.test_training.test_v7a_state_and_reports import _admin_token, _lab, _session, auth_header
from modules.training import reports


@pytest.mark.parametrize("field,value", [("result", "Neighbor absent"), ("target_device", "R3")])
def test_report_hash_covers_output_and_target(field, value):
    snapshot = {
        "session": SimpleNamespace(id=1, status="active", score=None, content_snapshot=None),
        "lab": SimpleNamespace(id=1, title="Observe OSPF", objectives=[], content_version=None),
        "logs": [{"id": 1, "command": "display ospf peer", "result": "Neighbor Full", "target_device": "R2"}],
        "faults": [],
    }
    before = reports.report_input_hash(reports.build_report_input(snapshot))
    changed = deepcopy(snapshot)
    changed["logs"][0][field] = value
    assert reports.report_input_hash(reports.build_report_input(changed)) != before


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["available", "empty", "unavailable"])
async def test_report_sources_match_prompt_and_preserve_status(client, test_session_factory, state):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)
    # Multiple complete paragraphs exercise bounded excerpt retention. A raw provider
    # field must not leak into the report prompt or saved source contract.
    hit = {"filename": "OSPF.md", "content": "# OSPF\n\n" + "邻居 Full 不代表所有业务可达。\n\n" * 260,
           "score": 0.8, "provider_debug": "INTERNAL_NOT_PROMPT"}
    knowledge = SimpleNamespace(search=AsyncMock(return_value=[hit, hit] if state == "available" else []))
    if state == "unavailable":
        knowledge.search.side_effect = RuntimeError("controlled outage")
    ai = SimpleNamespace(model_name="fixed-local-test", generate_report=AsyncMock(return_value={"summary": "Fixture report"}))
    with patch("modules.training.router._get_knowledge_service", return_value=knowledge), patch(
        "modules.training.router._get_ai_service", return_value=ai
    ):
        response = await client.post(f"/api/v1/training/sessions/{session_id}/report/generate",
                                     json={}, headers=auth_header(token))
        assert response.status_code == 200, response.text
        report = response.json()["report"]
        assert report["input_summary"]["knowledge_status"] == state
        prompt = ai.generate_report.await_args.kwargs["source_text"]
        assert "INTERNAL_NOT_PROMPT" not in prompt
        if state == "available":
            assert len(report["sources"]) == 1
            source = report["sources"][0]
            assert source["truncated"] is True
            assert len(source["prompt_text"]) <= 3000
            assert source["prompt_text"] in prompt
            assert source["prompt_sha256"] == hashlib.sha256(source["prompt_text"].encode()).hexdigest()
            assert source["version"] == hashlib.sha256(source["content"].encode()).hexdigest()
        else:
            assert not report["sources"]
        # Viewing and implicit reuse must not retry the failed provider or regenerate.
        read = await client.get(f"/api/v1/training/sessions/{session_id}/report", headers=auth_header(token))
        reused = await client.post(f"/api/v1/training/sessions/{session_id}/report/generate", json={}, headers=auth_header(token))
        assert read.json()["report"] == report
        assert reused.json()["reused"] is True
        assert knowledge.search.await_count == ai.generate_report.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [True, False])
@pytest.mark.parametrize("state", ["available", "empty", "unavailable"])
async def test_hint_retains_retrieval_state_with_or_without_environment_block(client, test_session_factory, blocked, state):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)
    hit = {"filename": "reference.md", "content": "# 现场核对\n\n记录不是设备执行证据。", "provider_debug": "INTERNAL_NOT_PROMPT"}
    knowledge = SimpleNamespace(search=AsyncMock(return_value=[hit] if state == "available" else []))
    if state == "unavailable":
        knowledge.search.side_effect = RuntimeError("controlled outage")
    ai = SimpleNamespace(coach_training=AsyncMock(return_value={"summary": "fixture", "coach_text": "fixture"}))
    with patch("modules.training.router._get_knowledge_service", return_value=knowledge), patch(
        "modules.training.router._get_ai_service", return_value=ai
    ), patch("modules.training.router.lab_environment", return_value={"allow_executable": not blocked, "reason": "未核验", "status": "unverified"}):
        response = await client.get(f"/api/v1/training/sessions/{session_id}/hint", headers=auth_header(token))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["knowledge_status"] == state
        assert body["config_blocked"] is blocked
        assert ai.coach_training.await_count == (0 if blocked else 1)
        if state == "available":
            source = body["sources"][0]
            assert "prompt_sha256" in source
            if not blocked:
                prompt = ai.coach_training.await_args.kwargs["scenario"]
                assert source["prompt_text"] in prompt
                assert "INTERNAL_NOT_PROMPT" not in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("knowledge_state", ["available", "empty", "unavailable"])
async def test_hint_model_failure_returns_local_template_with_source_status(client, test_session_factory, knowledge_state):
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)
    hit = {"filename": "reference.md", "content": "# 核对\n\n记录不等于已验证结果。"}
    knowledge = SimpleNamespace(search=AsyncMock(return_value=[hit] if knowledge_state == "available" else []))
    if knowledge_state == "unavailable":
        knowledge.search.side_effect = RuntimeError("controlled retrieval outage")
    ai = SimpleNamespace(coach_training=AsyncMock(side_effect=RuntimeError("controlled model outage")))
    with patch("modules.training.router._get_knowledge_service", return_value=knowledge), patch(
        "modules.training.router._get_ai_service", return_value=ai
    ), patch("modules.training.router.lab_environment", return_value={"allow_executable": True, "reason": "", "status": "not_required"}):
        response = await client.get(f"/api/v1/training/sessions/{session_id}/hint", headers=auth_header(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is True
    assert body["session_id"] == session_id and body["lab_id"] == lab_id
    assert body["knowledge_status"] == knowledge_state
    assert bool(body["sources"]) == (knowledge_state == "available")
    assert body["next_steps"] and body["coach_text"]
    assert knowledge.search.await_count == ai.coach_training.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,expected_degraded", [
    ("not JSON", True), ("{}", True), ("[]", True),
    ('{"summary": null, "coach_text": {"command": "not a string"}}', True),
    ('{"summary": "valid words", "next_steps": [{"command": "not a string"}]}', True),
    ('{"summary": "先核对原始记录", "next_steps": ["观察接口"]}', False),
])
async def test_hint_invalid_model_shape_is_explicit_local_template(client, test_session_factory, raw, expected_degraded):
    from modules.ai_text.llm_service import LLMService
    token = await _admin_token(test_session_factory)
    lab_id = await _lab(client, token)
    session_id = await _session(client, token, lab_id)
    provider = SimpleNamespace(name="fixed-local", generate=AsyncMock(return_value=raw))
    ai = LLMService(provider=provider)
    ai._log_request = AsyncMock()
    knowledge = SimpleNamespace(search=AsyncMock(return_value=[]))
    with patch("modules.training.router._get_knowledge_service", return_value=knowledge), patch(
        "modules.training.router._get_ai_service", return_value=ai
    ), patch("modules.training.router.lab_environment", return_value={"allow_executable": True, "reason": "", "status": "not_required"}):
        response = await client.get(f"/api/v1/training/sessions/{session_id}/hint", headers=auth_header(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is expected_degraded
    assert body["knowledge_status"] == "empty"
    assert "not a string" not in body["coach_text"]
    assert "实验步骤清单" not in body["coach_text"]  # Do not dump the internal prompt as an answer.
    assert provider.generate.await_count == 1
