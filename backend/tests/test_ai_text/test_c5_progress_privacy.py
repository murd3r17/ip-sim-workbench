"""Expose execution progress, never upstream deliberation text."""
import json
import uuid
from unittest.mock import AsyncMock

import pytest

from modules.ai_text import router
from tests.test_c3_request_api import api_case, events


@pytest.mark.asyncio
@pytest.mark.parametrize('with_answer', [True, False])
@pytest.mark.parametrize('path', ['/chat', '/chat/stream'])
async def test_deliberation_is_not_wire_data_or_recoverable_output(api_case, monkeypatch, with_answer, path):
    client, headers, _, retrieval = api_case
    marker = 'INTERNAL-DELIBERATION-NOT-A-USER-ANSWER'

    class Provider:
        model = 'offline-privacy-progress'
        calls = 0

        async def stream_parts(self, prompt, system=None):
            self.calls += 1
            # Total deliberation exceeds recovery result limit; dropping the
            # text also avoids failing an otherwise small, valid answer.
            for _ in range(40):
                yield {'kind': 'reasoning', 'text': marker * 2000}
            if with_answer:
                yield {'kind': 'content', 'text': '设备页提供设备列表和只读观察入口。'}

    provider = Provider()
    monkeypatch.setattr(router.SystemService, 'build_llm_provider', AsyncMock(return_value=provider))
    body = {'message': '这个页面能做什么？', 'context': {'route': '/devices'}, 'request_id': uuid.uuid4().hex}
    response = await client.post('/api/v1/ai/copilot' + path, headers=headers, json=body)
    assert response.status_code == 200
    assert marker not in response.text
    expected = 'ok' if with_answer else 'failed'
    if path == '/chat/stream':
        frames = events(response)
        progress = [e for e in frames if e['type'] == 'progress']
        assert len(progress) == 1 and progress[0]['stage'] == 'generating'
        assert progress[0]['message'] == '正在生成回答'
        assert not any(e['type'] == 'reasoning' for e in frames)
        assert frames[-1]['status'] == expected
    else:
        assert response.json()['status'] == expected
    recovered = await client.get('/api/v1/ai/copilot/requests/' + body['request_id'], headers=headers)
    assert recovered.status_code == 200 and marker not in recovered.text
    assert recovered.json()['state'] == ('completed' if with_answer else 'failed')
    assert provider.calls == 1
    retrieval.assert_not_awaited()
