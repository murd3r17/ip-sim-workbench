"""The assistant receives the visible A/B pair as saved, redacted history."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from modules.ai_text import router
from modules.deploy.models import ConfigVersion
from tests.test_ai_text.test_report_extensions import _seed_versions
from tests.test_c3_request_api import api_case, events


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('selection', ['saved', 'local', 'deleted', 'not_compared'])
async def test_current_config_comparison(api_case, test_session_factory, monkeypatch, path, selection):
    client, headers, provider, _ = api_case
    before, after = await _seed_versions(test_session_factory)
    prompts = []

    async def stream(prompt, system=None):
        prompts.append(prompt)
        yield {'kind': 'content', 'text': '按当前比对说明。'}

    monkeypatch.setattr(provider, 'stream_parts', stream)
    planner = AsyncMock(side_effect=AssertionError('Explaining a saved diff never plans a device read'))
    monkeypatch.setattr(provider, 'chat_completion', planner)
    comparison = {'kind': selection} if selection == 'local' else {
        'kind': 'saved', 'version_id_a': before, 'version_id_b': after if selection == 'saved' else 2_000_000,
    }
    if selection == 'not_compared':
        comparison = None
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': uuid4().hex,
        'message': '这两个本地配置文件改了什么？' if selection == 'local' else '这两个配置版本改了什么？',
        'context': {'route': '/config-versions', 'config_comparison': comparison},
        'history': [{'role': 'assistant', 'content': 'WRONG_OLD_COMPARISON'}],
        'page_data': 'WRONG_BROWSER_CONFIG',
    })
    assert response.status_code == 200
    if path == '/chat':
        trace = response.json()['trace']
        answer = response.json()['answer']
    else:
        frames = events(response)
        trace = next(event['trace'] for event in frames if event['type'] == 'done')
        answer = ''.join(event['text'] for event in frames if event['type'] == 'token')
    assert trace['tool_dispatch_attempts'] == 0
    for discarded in ('WRONG_OLD_COMPARISON', 'WRONG_BROWSER_CONFIG', '%SECRET%'):
        assert discarded not in answer + ''.join(prompts)
    if selection == 'saved':
        assert len(prompts) == 1
        prompt = prompts[0]
        assert f'"A": {{"id": {before}' in prompt
        assert f'"B": {{"id": {after}' in prompt
        assert '+  description uplink' in prompt
        assert 'b5-diff-dev' in prompt
    else:
        assert not prompts
        assert trace['model_calls'] == 0
        required = {'local': '服务端没有收到这两份文件', 'deleted': '两份快照未能同时回读',
                    'not_compared': '当前没有完成的 A/B 比对'}
        assert required[selection] in answer
        assert 'description uplink' not in answer
    planner.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_saved_name_change_follows_current_pair_and_discards_old_result(api_case, test_session_factory, monkeypatch, path):
    client, headers, _, retrieval = api_case
    a, b = await _seed_versions(test_session_factory)
    async with test_session_factory() as db:
        left, right = await db.get(ConfigVersion, a), await db.get(ConfigVersion, b)
        left.config_snapshot = 'sysname OriginShelf47\nlocal-user admin password cipher %PRIVATE%'
        right.config_snapshot = 'sysname TargetShelf82\nlocal-user admin password cipher %PRIVATE%'
        left.created_at = datetime(2026, 1, 12, 10, 0, tzinfo=timezone.utc)
        right.created_at = datetime(2026, 1, 12, 11, 0, tzinfo=timezone.utc)
        await db.commit()
    provider = AsyncMock(side_effect=AssertionError('The exact line can be read without a model'))
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', provider)

    async def ask(question, selection, history=None):
        response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
            'request_id': uuid4().hex, 'message': question,
            'context': {'route': '/config-versions', 'config_comparison': selection},
            'history': history or [], 'page_data': 'FAKE_PAGE_SYSNAME',
        })
        assert response.status_code == 200
        if path == '/chat':
            result = response.json()
            answer, trace = result['answer'], result['trace']
        else:
            frames = events(response)
            answer = ''.join(event['text'] for event in frames if event['type'] == 'token')
            trace = next(event['trace'] for event in frames if event['type'] == 'done')
        assert trace['model_calls'] == trace['tool_dispatch_attempts'] == 0
        assert all(sentinel not in answer for sentinel in ('FAKE_PAGE_SYSNAME', 'FAKE_PREVIOUS', '%PRIVATE%'))
        return answer

    current = {'kind': 'saved', 'version_id_a': a, 'version_id_b': b}
    first = await ask('只看现有两份存档，配置里主机名从哪个值变成哪个值？', current)
    assert 'A 为 V1' in first and 'B 为 V2' in first and '2026-01-12T10:00:00' in first and '2026-01-12T11:00:00' in first
    assert '从 `OriginShelf47` 变成 `TargetShelf82`' in first and 'b5-diff-dev' in first
    follow_up = '把两个快照的基准与目标对调了。请只按这次比对把同一行说明一下。'
    old = [{'role': 'assistant', 'content': 'FAKE_PREVIOUS ' + first}]
    reversed_pair = {'kind': 'saved', 'version_id_a': b, 'version_id_b': a}
    second = await ask(follow_up, reversed_pair, old)
    assert '从 `TargetShelf82` 变成 `OriginShelf47`' in second and 'A 为 V2' in second and 'B 为 V1' in second
    cleared = await ask(follow_up, None, old)
    assert '当前没有完成的 A/B 比对' in cleared and 'OriginShelf47' not in cleared and 'TargetShelf82' not in cleared
    provider.assert_not_awaited()
    retrieval.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_unnamed_line_after_swap_does_not_assume_name_if_multiple_lines_changed(api_case, test_session_factory, monkeypatch, path):
    client, headers, provider, retrieval = api_case
    a, b = await _seed_versions(test_session_factory)
    async with test_session_factory() as db:
        recent = await db.get(ConfigVersion, b)
        recent.config_snapshot = 'sysname PossibleName9\n interface GE0/0/1\n  description changed uplink'
        await db.commit()
    prompts = []

    async def stream(prompt, **kwargs):
        prompts.append(prompt)
        yield {'kind': 'content', 'text': '有多个变化项，请说明是哪一行。'}

    monkeypatch.setattr(provider, 'stream_parts', stream)
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': uuid4().hex, 'message': '我把基准和目标互换了，请按目前那一行说。',
        'context': {'route': '/config-versions', 'config_comparison': {'kind': 'saved', 'version_id_a': b, 'version_id_b': a}},
        'history': [{'role': 'assistant', 'content': 'UNTRUSTED_PREVIOUS_HOSTNAME'}],
    })
    assert response.status_code == 200 and len(prompts) == 1
    assert f'"A": {{"id": {b}' in prompts[0] and f'"B": {{"id": {a}' in prompts[0]
    assert 'UNTRUSTED_PREVIOUS_HOSTNAME' not in prompts[0]
    retrieval.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
@pytest.mark.parametrize('suffix,expected', [
    ('。前面的快照比对不用带上。', False),
    ('。别再沿用上一条的 A/B。', False),
    ('，也请结合这个会话已经讨论过的问题。', True),
])
async def test_cross_page_explicit_exclusion_removes_comparison_history_from_prompt(api_case, monkeypatch, path, suffix, expected):
    client, headers, provider, _ = api_case
    witness = []

    async def stream(prompt, **kwargs):
        witness.append('FORWARD_AND_REVERSE_SNAPSHOT_VALUES' in prompt)
        yield {'kind': 'content', 'text': '保留在手记里的记录需要另行核对。'}

    monkeypatch.setattr(provider, 'stream_parts', stream)
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json={
        'request_id': uuid4().hex, 'message': '换到实训了，请说明手记和核验的区别' + suffix,
        'context': {'route': '/training'}, 'history': [{'role': 'assistant', 'content': 'FORWARD_AND_REVERSE_SNAPSHOT_VALUES'}],
    })
    assert response.status_code == 200 and witness == [expected], response.text
