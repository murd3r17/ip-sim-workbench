"""Recipient setup operates only on an empty owned store and never on devices."""
from copy import deepcopy
import json

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from core.database import Base, _import_all_models
from modules.auth.models import User, UserRole
from modules.device.models import Device, Topology, TopologyLink, TopologyVersion, TopologyRuntimeCheck
from modules.system.models import SystemConfig
from modules.training.models import TrainingLab
from scripts.setup_full_workspace import import_devices, validate_manifest, export_allowlist, prepare_corpus, SetupRefused


@pytest.fixture
def manifest():
    return {"schema": 1, "topology": {"name": "接收方主拓扑"}, "devices": [
        {"hostname": f"R{n}", "mgmt_ip": "192.0.2.1", "ssh_port": 2200 + n,
         "device_type": "router", "vendor": "huawei", "model": "NE40E"} for n in (1, 2, 3)]}


@pytest_asyncio.fixture
async def factory():
    _import_all_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as db:
        db.add(User(username="recipient", hashed_password="test-hash", role=UserRole.ADMIN, is_active=True))
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_manifest_imports_actual_endpoints_and_existing_seven_labs_atomically(factory, manifest):
    receipt = await import_devices(factory, manifest, "recipient")
    assert receipt["created"] is True and len(receipt["device_ids"]) == 3 and len(receipt["lab_ids"]) == 7
    async with factory() as db:
        devices = list((await db.scalars(select(Device).order_by(Device.id))).all())
        assert {(d.mgmt_ip, d.ssh_port) for d in devices} == {(d["mgmt_ip"], d["ssh_port"]) for d in manifest["devices"]}
        assert all(d.status.value == "unknown" and d.password_encrypted is None and d.username_encrypted is None for d in devices)
        topology = await db.get(Topology, receipt["topology_id"])
        assert topology.topology_type.value == "main" and topology.device_count == 3
        assert await db.scalar(select(func.count()).select_from(TopologyVersion)) == 0
        assert await db.scalar(select(func.count()).select_from(TopologyRuntimeCheck)) == 0
        from modules.training.builtin_catalog import builtin_labs
        expected = {item["title"]: item for item in builtin_labs()}
        labs = list((await db.scalars(select(TrainingLab))).all())
        for lab in labs:
            assert lab.content_version == expected[lab.title]["content_version"]
            assert lab.environment_spec == expected[lab.title]["environment_spec"]
            assert lab.objectives == expected[lab.title]["objectives"]


@pytest.mark.asyncio
async def test_same_manifest_repeat_preserves_user_lab_edits_and_changed_manifest_refuses(factory, manifest):
    first = await import_devices(factory, manifest, "recipient")
    async with factory.begin() as db:
        lab = await db.get(TrainingLab, first["lab_ids"][0])
        lab.description = "接收方已修订"
        lab.content_version = "receiver-edited-v2"
        lab.environment_spec = {"label": "接收方自己的约束"}
    repeat = await import_devices(factory, deepcopy(manifest), "recipient")
    assert repeat["created"] is False and repeat["device_ids"] == first["device_ids"]
    async with factory() as db:
        kept = await db.get(TrainingLab, first["lab_ids"][0])
        assert kept.description == "接收方已修订"
        assert kept.content_version == "receiver-edited-v2"
        assert kept.environment_spec == {"label": "接收方自己的约束"}
    manifest["devices"][0]["ssh_port"] = 9999
    with pytest.raises(SetupRefused, match="manifest_changed"):
        await import_devices(factory, manifest, "recipient")


@pytest.mark.asyncio
async def test_existing_business_data_and_missing_admin_refuse_without_receipt_or_partial_rows(factory, manifest):
    with pytest.raises(SetupRefused, match="active_admin"):
        await import_devices(factory, manifest, "missing")
    async with factory.begin() as db:
        db.add(Topology(name="已有用户拓扑"))
    with pytest.raises(SetupRefused, match="business_database_not_empty"):
        await import_devices(factory, manifest, "recipient")
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(Device)) == 0
        assert await db.scalar(select(func.count()).select_from(SystemConfig)) == 0


@pytest.mark.parametrize("change", [
    lambda m: m["devices"].pop(), lambda m: m["devices"][0].update(password="do-not-accept"),
    lambda m: m["devices"][0].update(mgmt_ip="EDIT-ME"),
    lambda m: m["devices"][1].update(ssh_port=2201),
    lambda m: m["devices"][1].update(hostname="R1"),
    lambda m: m["devices"][0].update(ssh_port=True),
])
def test_manifest_rejects_placeholders_credentials_duplicate_endpoints_and_invalid_types(manifest, change):
    change(manifest)
    with pytest.raises(SetupRefused):
        validate_manifest(manifest)


@pytest.mark.asyncio
async def test_allowlist_requires_confirmed_current_baseline_and_uses_allocated_ids(factory, manifest):
    receipt = await import_devices(factory, manifest, "recipient")
    async with factory() as db:
        with pytest.raises(SetupRefused, match="confirmed_runtime_baseline_required"):
            await export_allowlist(db, receipt["topology_id"])
    from modules.device.baseline_service import TopologyBaselineService
    async with factory.begin() as db:
        db.add(TopologyLink(topology_id=receipt["topology_id"], source_device_id=receipt["device_ids"][0], target_device_id=receipt["device_ids"][1], source_interface="GE0/0/0", target_interface="GE0/0/0"))
        await db.flush()
        snapshot = await TopologyBaselineService._snapshot(db, receipt["topology_id"])
        version = TopologyVersion(topology_id=receipt["topology_id"], version=8, batch_id="fixture", source_name="pending", source_type="ensp", snapshot_json=json.dumps(snapshot), created_by=1)
        db.add(version)
        await db.flush()
        check = TopologyRuntimeCheck(topology_id=receipt["topology_id"], confirmed_version_id=version.id, status="matched", ssh_success=3, ssh_failed=0, observed_links_json='[{"source_device":"R1","target_device":"R2"}]', diff_json="{}")
        db.add(check)
        await db.flush()
        version.source_name = f"ensp-runtime-check-{check.id}"
    async with factory() as db:
        values = await export_allowlist(db, receipt["topology_id"])
        assert values["DEPLOY_ALLOWLIST_DEVICE_IDS"] == ",".join(map(str, receipt["device_ids"]))
        assert values["DEPLOY_ALLOWLIST_MGMT_IPS"] == "192.0.2.1"
        assert values["DEPLOY_ALLOWLIST_BASELINE_VERSION"] == "8"
    async with factory.begin() as db:
        (await db.get(Device, receipt["device_ids"][0])).ssh_port = 9999
    async with factory() as db:
        with pytest.raises(SetupRefused, match="baseline_drift"):
            await export_allowlist(db, receipt["topology_id"])


def test_prepare_corpus_admission_unique_ascii_names_and_no_overwrite(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "00-index.md").write_text("# index", encoding="utf-8")
    (corpus / "ignore.md").write_text("---\ningest: false\n---\n# No", encoding="utf-8")
    (corpus / "教材.md").write_text("---\ningest: true\n---\n# OSPF\nText", encoding="utf-8")
    target = tmp_path / "upload"
    report = prepare_corpus(corpus, target, expected_count=1)
    assert report["document_count"] == 1 and (target / "doc-001.md").exists()
    assert report["documents"][0]["source"] == "教材.md"
    with pytest.raises(SetupRefused, match="output_already_exists"):
        prepare_corpus(corpus, target, expected_count=1)
    with pytest.raises(SetupRefused, match="corpus_count_mismatch"):
        prepare_corpus(corpus, tmp_path / "wrong", expected_count=135)
    assert not (tmp_path / "wrong").exists()


def test_shipped_corpus_stages_exactly_135_body_documents(tmp_path):
    from pathlib import Path
    corpus = Path(__file__).resolve().parents[2] / "knowledge/corpus/huawei-ip"
    report = prepare_corpus(corpus, tmp_path / "upload")
    assert report["document_count"] == 135 and report["uploaded"] is False
    assert len({row["file"] for row in report["documents"]}) == 135
    assert all(not row["source"].lower().endswith("00-index.md") for row in report["documents"])


@pytest.mark.asyncio
async def test_failure_after_device_inserts_rolls_back_entire_initialization(factory, manifest, monkeypatch):
    from scripts import seed_training_labs
    from sqlalchemy.exc import IntegrityError
    monkeypatch.setattr(seed_training_labs, "LABS", [{"title": None, "description": "fixture", "objectives": []}])
    with pytest.raises(IntegrityError):
        await import_devices(factory, manifest, "recipient")
    async with factory() as db:
        for model in (Device, Topology, TrainingLab, SystemConfig):
            assert await db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.asyncio
async def test_inventory_only_allowlist_requires_matching_human_confirmation_audit(factory, manifest):
    from modules.auth.models import AuditLog
    from modules.device.baseline_service import TopologyBaselineService
    receipt = await import_devices(factory, manifest, "recipient")
    async with factory.begin() as db:
        snapshot = await TopologyBaselineService._snapshot(db, receipt["topology_id"])
        db.add(TopologyVersion(topology_id=receipt["topology_id"], version=2, batch_id="test", source_name="inventory.xlsx", source_type="inventory_only", created_by=1, snapshot_json=json.dumps(snapshot)))
    async with factory() as db:
        with pytest.raises(SetupRefused, match="explicit_import_confirmation_audit_required"):
            await export_allowlist(db, receipt["topology_id"])
    async with factory.begin() as db:
        db.add(AuditLog(user_id=1, username="recipient", module="device", action="topology_baseline_import", resource_type="topology", resource_id=str(receipt["topology_id"]),
                        detail=str({"version": 2, "source_type": "inventory_only", "inventory_only": True, "device_count": 3, "link_count": 0}), result="success"))
    async with factory() as db:
        values = await export_allowlist(db, receipt["topology_id"])
        assert values["DEPLOY_ALLOWLIST_BASELINE_VERSION"] == "2"


def test_default_deployment_allowlist_is_empty():
    from core.config import Settings
    settings = Settings(_env_file=None)
    assert not settings.deploy_allowlist_device_ids
    assert not settings.deploy_allowlist_mgmt_ips
    assert settings.deploy_allowlist_topology_id == settings.deploy_allowlist_baseline_version == 0
