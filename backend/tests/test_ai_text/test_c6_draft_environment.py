from datetime import datetime,timezone
import pytest

from modules.ai_text.trusted_context import ResolvedDraftTarget,TrustedPageData,sanitize
from modules.trust.models import EnvironmentProfile
from modules.trust.service import environment_hash


async def ready_environment(db,*,device_id=3,version='v1',status='ready'):
    row=EnvironmentProfile(name='authored-draft-environment',version=version,status=status,revision=1,
        devices=[{'device_id':device_id}],protections=[{'kind':'management','target':'R3:LoopBack77'}],
        last_preflight_status=status,last_preflight_mode='sim',last_preflight_at=datetime.now(timezone.utc))
    db.add(row);await db.flush()
    row.content_hash=environment_hash(row);await db.commit()
    return row


@pytest.mark.asyncio
async def test_unique_verified_server_environment_is_required(client,test_session_factory):
    # client owns per-case cleanup of the session-scoped in-memory database.
    from modules.ai_text.draft_environment import resolve_draft_environment
    target=ResolvedDraftTarget(3,'R3',device_model='NE40E')
    async with test_session_factory() as db:
        missing=await resolve_draft_environment(db,target)
        assert not missing.verified and missing.reason_code=='environment_unbound'
        row=await ready_environment(db)
        policy=await resolve_draft_environment(db,target)
        assert policy.verified and policy.environment_id==row.id and policy.revision==1 and policy.mode=='sim'
        unknown=await resolve_draft_environment(db,None)
        assert not unknown.verified and unknown.reason_code=='target_unresolved'


@pytest.mark.asyncio
@pytest.mark.parametrize('change',[
    {'status':'draft'},{'status':'mismatch'},{'last_preflight_status':'unknown'},
    {'last_preflight_mode':'unknown'},{'content_hash':'wrong'},
    {'devices':[{'device_id':3,'role':'changed-after-preflight'}]},
])
async def test_unverified_or_modified_environment_does_not_allow_bound_draft(client,test_session_factory,change):
    from modules.ai_text.draft_environment import resolve_draft_environment
    async with test_session_factory() as db:
        row=await ready_environment(db)
        for key,value in change.items():setattr(row,key,value)
        await db.commit()
        assert not (await resolve_draft_environment(db,ResolvedDraftTarget(3,'R3'))).verified


@pytest.mark.asyncio
async def test_ambiguous_profiles_need_actual_verified_evidence_not_client_version(client,test_session_factory):
    from modules.ai_text.draft_environment import resolve_draft_environment
    target=ResolvedDraftTarget(3,'R3')
    async with test_session_factory() as db:
        first=await ready_environment(db,version='v1')
        await ready_environment(db,version='v2')
        client=sanitize('{"device":"R3","source":"real","environment_id":1,"environment_version":"v1"}')
        assert not (await resolve_draft_environment(db,target,page=client)).verified
        actual=TrustedPageData('{}',{'trusted':True,'environment_id':first.id,'device_id':3,
            'environment_revision':first.revision,'environment_version':first.version})
        assert (await resolve_draft_environment(db,target,page=actual)).environment_id==first.id
        actual.meta['environment_revision']=0
        assert not (await resolve_draft_environment(db,target,page=actual)).verified
        wrong_device=TrustedPageData('{}',{'trusted':True,'environment_id':first.id,'device_id':2})
        assert not (await resolve_draft_environment(db,target,page=wrong_device)).verified


@pytest.mark.asyncio
async def test_policy_recheck_rejects_generation_time_revision_drift(client,test_session_factory):
    from modules.ai_text.draft_environment import resolve_draft_environment,current_draft_environment
    async with test_session_factory() as first:
        row=await ready_environment(first)
        policy=await resolve_draft_environment(first,ResolvedDraftTarget(3,'R3'))
        assert await current_draft_environment(first,policy)
        async with test_session_factory() as changed:
            fresh=await changed.get(EnvironmentProfile,row.id)
            fresh.revision+=1;fresh.content_hash=environment_hash(fresh)
            await changed.commit()
        assert not await current_draft_environment(first,policy)


@pytest.mark.asyncio
async def test_preflight_mode_change_does_not_promote_sim_policy_to_real(client,test_session_factory):
    from modules.ai_text.draft_environment import resolve_draft_environment,current_draft_environment
    async with test_session_factory() as db:
        row=await ready_environment(db)
        policy=await resolve_draft_environment(db,ResolvedDraftTarget(3,'R3'))
        row.last_preflight_mode='real';await db.commit()
        assert not await current_draft_environment(db,policy)
