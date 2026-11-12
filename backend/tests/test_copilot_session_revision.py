"""Optimistic conversation saves preserve both stale clients and the server version."""
import pytest

from tests.test_copilot_session_idor import _make_user, auth_header


@pytest.mark.asyncio
async def test_stale_and_unversioned_saves_do_not_overwrite_history(client, test_session_factory):
    token = await _make_user(test_session_factory, "revision-owner", "user")
    url = "/api/v1/ai/copilot/sessions/revision-conversation"
    headers = auth_header(token)
    created = await client.put(url, headers=headers, json={"title": "first", "messages": []})
    assert created.status_code == 200
    assert created.json()["revision"] == 1
    # A client that lost the create response must not blindly overwrite that ID.
    retry = await client.put(url, headers=headers, json={"title": "retry after response loss", "messages": []})
    assert retry.status_code == 409
    first_tab = (await client.get(url, headers=headers)).json()
    second_tab = (await client.get(url, headers=headers)).json()
    updated = await client.put(url, headers=headers, json={
        "title": "newest", "messages": [{"role": "user", "content": "keep this message"}],
        "revision": first_tab["revision"],
    })
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    for revision in (None, second_tab["revision"]):
        stale = await client.put(url, headers=headers, json={"title": "stale", "messages": [], "revision": revision})
        assert stale.status_code == 409
    current = (await client.get(url, headers=headers)).json()
    assert current["title"] == "newest"
    assert current["revision"] == 2
    assert current["messages"][0]["content"] == "keep this message"
    listing = (await client.get("/api/v1/ai/copilot/sessions", headers=headers)).json()
    assert next(item for item in listing if item["id"] == current["id"])["revision"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_deleted_conversation_is_not_resurrected_by_stale_save(client, test_session_factory, legacy):
    token = await _make_user(test_session_factory, "deleted-owner", "user")
    headers = auth_header(token)
    url = "/api/v1/ai/copilot/sessions/deleted-conversation"
    created = await client.put(url, headers=headers, json={"title": "first", "messages": []})
    revision = created.json()["revision"]
    if legacy:
        from sqlalchemy import update
        from modules.ai_text.models import CopilotConversation
        async with test_session_factory() as db:
            await db.execute(update(CopilotConversation).where(CopilotConversation.id == "deleted-conversation").values(revision=0))
            await db.commit()
        revision = 0
    assert (await client.delete(url, headers=headers)).status_code == 200
    stale = await client.put(url, headers=headers, json={"title": "resurrected", "messages": [], "revision": revision})
    assert stale.status_code == 409
    assert (await client.get(url, headers=headers)).json()["exists"] is False


@pytest.mark.asyncio
async def test_migrated_zero_revision_can_be_updated_with_explicit_version(client, test_session_factory):
    from modules.ai_text.models import CopilotConversation
    from sqlalchemy import update

    token = await _make_user(test_session_factory, "legacy-owner", "user")
    headers = auth_header(token)
    url = "/api/v1/ai/copilot/sessions/legacy-conversation"
    assert (await client.put(url, headers=headers, json={"title": "old", "messages": []})).status_code == 200
    async with test_session_factory() as db:
        await db.execute(update(CopilotConversation).where(CopilotConversation.id == "legacy-conversation").values(revision=0))
        await db.commit()
    legacy = (await client.get(url, headers=headers)).json()
    assert legacy["revision"] == 0
    saved = await client.put(url, headers=headers, json={"title": "updated", "messages": [], "revision": legacy["revision"]})
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
