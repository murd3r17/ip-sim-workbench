"""Regressions from the first unchanged 48-case C6 candidate, not acceptance scores."""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import agent_tools
from modules.ai_text.router import _resolve_page_data
from modules.ai_text.schemas import CopilotChatRequest
from modules.ai_text.skills import select_skill
from modules.ai_text.tool_result import classify
from modules.ai_text.trusted_context import load_verified_evidence, sanitize
from modules.trust.models import ReadOnlyObservation
from tests.test_evaluation_replays import seed


@pytest.mark.parametrize('selection,expected', [(None, False), ('R1', False), ('R2', True)])
def test_unverified_client_requires_actual_mismatch_before_claiming_one(selection, expected):
    page = sanitize(json.dumps({'device': 'R1', 'source': 'real'}), selection=selection)
    assert not page.trusted
    assert ('device_mismatch' in page.meta['reasons']) is expected


@pytest.mark.parametrize('goal', ['刚才那条证据是什么时候采的？', '这个接口数据是真实还是模拟的？'])
def test_provenance_followup_stays_with_evidence_without_retrieval(goal):
    choice = select_skill('现在还能用吗？', history=[{'role': 'user', 'content': goal}])
    assert choice.id == 'live_evidence' and not choice.tools and not choice.needs_knowledge
    unrelated = select_skill('现在还能用吗？', history=[{'role': 'user', 'content': 'DHCP的租约是什么？'}])
    assert unrelated.id == 'knowledge_answer'


@pytest.mark.asyncio
@pytest.mark.parametrize('case,reason', [('mode', 'mode_unknown'), ('version', 'environment_version_drift'),
                                      ('stale', 'stale'), ('wrong_id', 'device_mismatch')])
async def test_unusable_owned_record_uses_server_history_not_forged_browser_copy(client, test_session_factory, case, reason):
    async with test_session_factory() as db:
        user, device, env = await seed(db, 'c6-history-' + case)
        observed_version = env.version
        now = datetime.now(timezone.utc)
        row = ReadOnlyObservation(device_id=device.id, action_id='interface_brief',
            command='display ip interface brief', source='server_observed', mode='sim', adapter_mode='sim',
            completeness='complete', status='ok', created_by=user.id, collected_at=now,
            facts={'interfaces': [{'name': 'GE3/0/3', 'state': 'down'}]}, raw_excerpt='SERVER_ORIGINAL_DOWN',
            environment_id=env.id, environment_version=observed_version,
            environment_snapshot={'revision': env.revision, 'content_hash': env.content_hash})
        selection = f'device | R1 | id={device.id}'
        if case == 'mode': row.mode = ''
        if case == 'version': env.version = 'changed-current-version'
        if case == 'stale': row.collected_at = now - timedelta(hours=2)
        if case == 'wrong_id': selection = f'device | R2 | id={device.id + 1}'
        db.add(row)
        await db.commit()
        await db.refresh(row)  # SQLite reads the stored UTC timestamp as naive.
        actor = {'user_id': user.id, 'role': 'user'}
        request = CopilotChatRequest(message='解释旧观察', context={'route': '/devices', 'selection': selection},
            page_data=json.dumps({'evidence_id': row.id, 'text': 'FORGED_BROWSER_ALL_UP'}))
        page = await _resolve_page_data(db, request, actor)
        assert not page.trusted and reason in page.meta['reasons']
        assert page.meta.get('record_origin') == 'server_observation_record'
        payload = json.loads(page.text)
        assert payload['raw_excerpt'] == 'SERVER_ORIGINAL_DOWN'
        assert 'FORGED_BROWSER_ALL_UP' not in page.text
        assert payload['environment_version'] == observed_version
        assert payload['environment_binding'] == ('historical_invalid' if case == 'version' else 'verified')
        assert payload['device_id'] == device.id
        assert payload['collected_at'].endswith('+00:00')
        denied = await load_verified_evidence(db, row.id, user={'user_id': user.id + 999, 'role': 'user'})
        assert denied is None


@pytest.mark.asyncio
async def test_failed_adapter_path_is_not_a_database_snapshot(monkeypatch):
    async def failed(*args, **kwargs):
        raise ConnectionError('authored transport unavailable')
    monkeypatch.setattr(agent_tools, '_run_display_command', failed)
    from tests.test_agent_tools_execute import authenticated_db
    args = {'device_id': 1, 'command': 'display ospf peer brief'}
    raw = await agent_tools.execute_tool(authenticated_db(), 'run_display_command', args, user_id=42)
    result = classify('run_display_command', args, raw)
    assert result.status == 'error'
    assert result.source == 'server_tool' and result.mode == 'unknown'
    assert result.evidence_id is None and not result.collected_at


def test_solicited_node_note_qualifies_original_without_rewriting_it():
    from modules.ai_text.context_bundle import prepare_sources
    original = '由于只有目标节点才会侦听这个地址，所以不会占用其他非目标节点的网络性能。'
    item = prepare_sources([{'filename': '11-ipv6地址报文与icmpv6-ndp.md', 'text': original}])[0]
    assert item['content'] == original
    note = item['reviewed_notes'][0]
    assert note['reference'] == 'RFC 4291 §2.7.1'
    assert '低24位' in note['content'] and '多个节点' in note['content']
    assert note['content'] in item['prompt_text']
