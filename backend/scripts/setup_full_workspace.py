"""Recipient-owned full setup: local inventory import, baseline export, corpus staging.

No device/model/knowledge network calls. Import is restricted to an initialized
database with no business rows, and never overwrites an existing workspace.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
from copy import deepcopy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
RECEIPT_KEY = "setup.full_workspace.v1"


class SetupRefused(ValueError):
    """Fixed, non-secret failure codes suitable for CLI output."""


def require(condition, code):
    if not condition:
        raise SetupRefused(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_manifest(value):
    require(isinstance(value, dict) and set(value) == {"schema", "topology", "devices"}
            and type(value["schema"]) is int and value["schema"] == 1, "invalid_manifest_schema")
    topology = value["topology"]
    require(isinstance(topology, dict) and set(topology) == {"name"}
            and isinstance(topology["name"], str) and 0 < len(topology["name"].strip()) <= 128,
            "invalid_topology")
    devices = value["devices"]
    require(isinstance(devices, list) and len(devices) == 3, "exactly_three_devices_required")
    required = {"hostname", "mgmt_ip", "ssh_port", "device_type", "vendor"}
    normalized = []
    for device in devices:
        require(isinstance(device, dict) and required <= set(device)
                and set(device) <= required | {"model"}, "unexpected_device_fields_credentials_forbidden")
        require(isinstance(device["hostname"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", device["hostname"]), "invalid_hostname")
        require(type(device["ssh_port"]) is int and 0 < device["ssh_port"] < 65536, "invalid_ssh_port")
        try:
            address = ipaddress.ip_address(device["mgmt_ip"])
        except (TypeError, ValueError):
            raise SetupRefused("invalid_management_ip") from None
        require(not address.is_unspecified and not address.is_multicast, "invalid_management_ip")
        require(device["device_type"] in {"router", "switch_l2", "switch_l3", "firewall", "server", "other"}
                and device["vendor"] in {"huawei", "h3c", "other"}, "invalid_device_kind")
        model = device.get("model") or ""
        require(isinstance(model, str) and len(model) <= 64 and "\n" not in model, "invalid_model")
        normalized.append({**device, "mgmt_ip": str(address), "model": model})
    require(len({d["hostname"] for d in normalized}) == 3, "duplicate_hostname")
    require(len({(d["mgmt_ip"], d["ssh_port"]) for d in normalized}) == 3, "duplicate_endpoint")
    return {"schema": 1, "topology": {"name": topology["name"].strip()},
            "devices": sorted(normalized, key=lambda d: d["hostname"])}


async def import_devices(factory, manifest, admin_username):
    from sqlalchemy import func, inspect, select, table
    from core.database import _import_all_models
    from modules.auth.models import User, UserRole
    from modules.device.models import Device, DeviceStatus, DeviceType, DeviceVendor, Topology, TopologyType
    from modules.system.models import SystemConfig
    from modules.training.models import TrainingLab, LabStatus
    from scripts.seed_training_labs import LABS

    _import_all_models()
    manifest = validate_manifest(manifest)
    digest = hashlib.sha256(canonical(manifest).encode("utf-8")).hexdigest()
    # Receipt uniqueness serializes competing imports. Any failure rolls back the
    # receipt, inventory and labs together, including a duplicate-key loser.
    async with factory.begin() as db:
        admin = await db.scalar(select(User).where(User.username == admin_username, User.role == UserRole.ADMIN, User.is_active.is_(True)))
        require(admin is not None, "active_admin_required")
        existing = await db.scalar(select(SystemConfig).where(SystemConfig.config_key == RECEIPT_KEY))
        if existing:
            receipt = json.loads(existing.config_value)
            require(receipt.get("manifest_sha256") == digest, "manifest_changed_existing_import")
            topology = await db.get(Topology, receipt["topology_id"])
            require(topology is not None, "existing_import_inventory_changed")
            rows = list((await db.scalars(select(Device).where(Device.topology_id == topology.id).order_by(Device.hostname))).all())
            require([d.id for d in rows] == receipt["device_ids"] and len(rows) == 3, "existing_import_inventory_changed")
            for row, wanted in zip(rows, manifest["devices"]):
                actual = {"hostname": row.hostname, "mgmt_ip": row.mgmt_ip, "ssh_port": row.ssh_port,
                          "device_type": row.device_type.value, "vendor": row.vendor.value, "model": row.model or ""}
                require(actual == wanted, "existing_import_inventory_changed")
            found_labs = await db.scalar(select(func.count()).select_from(TrainingLab).where(TrainingLab.id.in_(receipt["lab_ids"])))
            require(found_labs == len(receipt["lab_ids"]), "existing_import_labs_changed")
            return {**receipt, "created": False}
        marker = SystemConfig(config_key=RECEIPT_KEY, config_value="pending", updated_by=admin.username,
                              description="First full workspace import receipt; not device credentials")
        db.add(marker)
        await db.flush()
        connection = await db.connection()
        tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
        for name in tables:
            if name not in {"alembic_version", "user", "system_config", "audit_log"}:
                require(await db.scalar(select(func.count()).select_from(table(name))) == 0, "business_database_not_empty")
        topology = Topology(name=manifest["topology"]["name"], topology_type=TopologyType.MAIN,
                            owner_id=admin.id, device_count=3, status="active", topology_source="manual")
        db.add(topology)
        await db.flush()
        devices = [Device(**{**item, "device_type": DeviceType(item["device_type"]), "vendor": DeviceVendor(item["vendor"])},
                          topology_id=topology.id, status=DeviceStatus.UNKNOWN) for item in manifest["devices"]]
        db.add_all(devices)
        labs = [TrainingLab(title=item["title"], description=item["description"], topology_id=topology.id,
                            instructor_id=admin.id, objectives=deepcopy(item["objectives"]), scoring_rules={},
                            time_limit_minutes=item.get("time_limit_minutes", 45), is_sandbox=item.get("is_sandbox", False),
                            content_version=item.get("content_version"),
                            environment_spec=deepcopy(item.get("environment_spec")),
                            status=LabStatus.READY) for item in LABS]
        db.add_all(labs)
        await db.flush()
        receipt = {"schema": 1, "manifest_sha256": digest, "topology_id": topology.id,
                   "device_ids": [d.id for d in devices], "lab_ids": [lab.id for lab in labs]}
        marker.config_value = canonical(receipt)
        return {**receipt, "created": True}


async def export_allowlist(db, topology_id):
    from sqlalchemy import select
    from modules.auth.models import AuditLog
    from modules.device.baseline_service import TopologyBaselineService
    from modules.device.models import TopologyRuntimeCheck

    version = await TopologyBaselineService._latest_version(db, topology_id)
    require(version is not None and version.source_type in {"ensp", "excel", "inventory_only"} and version.created_by is not None,
            "confirmed_runtime_baseline_required")
    current = await TopologyBaselineService._snapshot(db, topology_id)
    require(canonical(current) == canonical(json.loads(version.snapshot_json)), "baseline_drift_recheck_required")
    if version.source_type == "ensp":
        checks = list((await db.scalars(select(TopologyRuntimeCheck).where(
            TopologyRuntimeCheck.topology_id == topology_id, TopologyRuntimeCheck.confirmed_version_id == version.id))).all())
        require(len(checks) == 1, "confirmed_runtime_baseline_required")
        check = checks[0]
        require(version.source_name == f"ensp-runtime-check-{check.id}" and check.ssh_success == 3 and check.ssh_failed == 0
                and bool(json.loads(check.observed_links_json)) and not json.loads(check.errors_json or "[]"),
                "complete_runtime_baseline_required")
    else:
        audits = list((await db.scalars(select(AuditLog).where(
            AuditLog.module == "device", AuditLog.action == "topology_baseline_import",
            AuditLog.resource_type == "topology", AuditLog.resource_id == str(topology_id),
            AuditLog.user_id == version.created_by, AuditLog.result == "success"))).all())
        confirmed = False
        for audit in audits:
            try:
                detail = ast.literal_eval(audit.detail or "{}")
            except (SyntaxError, ValueError):
                continue
            if (isinstance(detail, dict) and detail.get("version") == version.version
                    and detail.get("source_type") == version.source_type
                    and detail.get("inventory_only") is (version.source_type == "inventory_only")
                    and detail.get("device_count") == 3 and detail.get("link_count") == len(current["links"])):
                confirmed = True
        require(confirmed, "explicit_import_confirmation_audit_required")
    devices = current["devices"]
    require(len(devices) == 3 and (bool(current["links"]) or version.source_type == "inventory_only")
            and len({(d["mgmt_ip"], d["ssh_port"]) for d in devices}) == 3, "three_confirmed_devices_required")
    require(version.source_type != "inventory_only" or not current["links"], "inventory_only_links_must_be_empty")
    # Use IP parsing to keep the generated dotenv fragment literal and portable.
    ips = sorted({str(ipaddress.ip_address(d["mgmt_ip"])) for d in devices})
    return {"DEPLOY_ALLOWLIST_DEVICE_IDS": ",".join(str(d["id"]) for d in sorted(devices, key=lambda d: d["id"])),
            "DEPLOY_ALLOWLIST_MGMT_IPS": ",".join(ips), "DEPLOY_ALLOWLIST_TOPOLOGY_ID": str(topology_id),
            "DEPLOY_ALLOWLIST_BASELINE_VERSION": str(version.version)}


def prepare_corpus(corpus, output, expected_count=135):
    from modules.knowledge.local_provider import _frontmatter, _INDEX_NAMES, _split_chunks, _tokenize

    corpus, output = Path(corpus).resolve(), Path(output).resolve()
    require(corpus.is_dir(), "bundled_corpus_missing")
    require(not output.is_relative_to(corpus), "output_must_be_outside_corpus")
    require(not output.exists(), "output_already_exists")
    eligible = []
    for path in sorted(corpus.rglob("*.md")):
        require(not path.is_symlink() and path.resolve().is_relative_to(corpus), "corpus_symlink_forbidden")
        if path.name.lower() in _INDEX_NAMES:
            continue
        raw = path.read_bytes()
        metadata, body = _frontmatter(raw.decode("utf-8-sig"))
        if metadata.get("ingest", "true").lower() == "true" and any(_tokenize(chunk) for chunk in _split_chunks(body)):
            eligible.append((path, raw))
    require(len(eligible) == expected_count, "corpus_count_mismatch")
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for number, (path, raw) in enumerate(eligible, 1):
        filename = f"doc-{number:03}.md"
        (output / filename).write_bytes(raw)
        rows.append({"file": filename, "source": path.relative_to(corpus).as_posix(),
                     "sha256": hashlib.sha256(raw).hexdigest()})
    report = {"schema": 1, "document_count": len(rows), "documents": rows, "uploaded": False}
    (output / "corpus-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


async def database_action(args):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from core.config import get_settings
    from core.database import resolve_database_url, _import_all_models
    from core.migrations import assert_schema_ready

    settings = get_settings()
    url = resolve_database_url(settings)
    parsed = make_url(url)
    require(parsed.get_backend_name() == "mysql" and settings.device_mode == "ssh", "full_mysql_ssh_profile_required")
    require(bool(args.expect_database) and parsed.database == args.expect_database, "explicit_database_name_mismatch")
    _import_all_models()
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(assert_schema_ready)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        if args.action == "import-devices":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
            return await import_devices(factory, manifest, settings.admin_username)
        async with factory() as db:
            values = await export_allowlist(db, args.topology_id)
            from modules.device.baseline_service import TopologyBaselineService
            basis = (await TopologyBaselineService._latest_version(db, args.topology_id)).source_type
        require(not args.output.exists(), "output_already_exists")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(f"# Human-confirmed {basis}; inventory_only confirms target identity, not links. Does not enable writes.\n")
            output.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
        return {"exported": True, "baseline_source": basis, "topology_id": args.topology_id, "baseline_version": int(values["DEPLOY_ALLOWLIST_BASELINE_VERSION"])}
    finally:
        await engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    importer = subparsers.add_parser("import-devices")
    importer.add_argument("--manifest", type=Path, required=True)
    importer.add_argument("--expect-database", required=True)
    exporter = subparsers.add_parser("export-allowlist")
    exporter.add_argument("--expect-database", required=True)
    exporter.add_argument("--topology-id", type=int, required=True)
    exporter.add_argument("--output", type=Path, required=True)
    corpus = subparsers.add_parser("prepare-corpus")
    corpus.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare-corpus":
            report = prepare_corpus(ROOT / "knowledge/corpus/huawei-ip", args.output)
            result = {"document_count": report["document_count"], "uploaded": False}
        else:
            result = asyncio.run(database_action(args))
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "reason": str(exc) if isinstance(exc, SetupRefused) else type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
