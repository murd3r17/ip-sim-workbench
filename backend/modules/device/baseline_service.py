"""Topology baseline import, versioning, diff, and rollback services."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from uuid import uuid4

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.device.models import (
    Device,
    DeviceStatus,
    DeviceType,
    DeviceVendor,
    Topology,
    TopologyLink,
    TopologyRuntimeCheck,
    TopologyVersion,
)
from modules.device.schemas import ImportIssue, TopologyImportPreview
from modules.device.topology_import import TopologyExcelParser
from modules.device.lldp_parser import normalize_interface_name
from core.logger import get_logger

logger = get_logger("topology")


def _device_type(hostname: str) -> DeviceType:
    return DeviceType.SWITCH_L3 if hostname.upper().startswith("S-") else DeviceType.ROUTER


def _network_role(hostname: str) -> str:
    name = hostname.upper()
    if name.startswith(("BB-", "PB-")):
        return "core"
    if name.startswith("S-"):
        return "access"
    return "aggregation"


def _canonical_pair(link: dict) -> frozenset[str]:
    return frozenset((link["source_device"], link["target_device"]))


def _canonical_link(link: dict) -> tuple:
    source = (link["source_device"], normalize_interface_name(link["source_interface"]))
    target = (link["target_device"], normalize_interface_name(link["target_interface"]))
    source_ip, target_ip = link.get("source_ip"), link.get("target_ip")
    if target < source:
        source, target = target, source
        source_ip, target_ip = target_ip, source_ip
    return (
        *source,
        *target,
        source_ip,
        target_ip,
        link.get("link_type"),
        link.get("status"),
        link.get("discovery_source"),
        link.get("source_type"),
    )


def snapshot_diff(previous: dict | None, current: dict) -> dict:
    if not previous:
        return {
            "added_devices": len(current["devices"]),
            "removed_devices": 0,
            "changed_devices": 0,
            "added_links": len(current["links"]),
            "removed_links": 0,
            "changed_links": 0,
        }

    old_devices = {item["hostname"]: item for item in previous["devices"]}
    new_devices = {item["hostname"]: item for item in current["devices"]}
    old_links = defaultdict(Counter)
    new_links = defaultdict(Counter)
    for item in previous["links"]:
        old_links[_canonical_pair(item)][_canonical_link(item)] += 1
    for item in current["links"]:
        new_links[_canonical_pair(item)][_canonical_link(item)] += 1
    common_devices = old_devices.keys() & new_devices.keys()
    added_links = removed_links = changed_links = 0
    for pair in old_links.keys() | new_links.keys():
        old_remaining = old_links[pair] - new_links[pair]
        new_remaining = new_links[pair] - old_links[pair]
        changed = min(old_remaining.total(), new_remaining.total())
        changed_links += changed
        removed_links += old_remaining.total() - changed
        added_links += new_remaining.total() - changed
    return {
        "added_devices": len(new_devices.keys() - old_devices.keys()),
        "removed_devices": len(old_devices.keys() - new_devices.keys()),
        "changed_devices": sum(old_devices[key] != new_devices[key] for key in common_devices),
        "added_links": added_links,
        "removed_links": removed_links,
        "changed_links": changed_links,
    }


class TopologyBaselineService:
    @staticmethod
    async def preview(db: AsyncSession, topology_id: int, content: bytes, *, inventory_only: bool = False) -> TopologyImportPreview:
        if not await db.get(Topology, topology_id):
            raise ValueError(f"拓扑不存在: {topology_id}")
        preview = TopologyExcelParser.parse(content, inventory_only=inventory_only)

        imported_ips = {item.mgmt_ip for item in preview.devices}
        if imported_ips:
            result = await db.execute(select(Device).where(or_(
                Device.mgmt_ip.in_(imported_ips),
                and_(Device.topology_id == topology_id, Device.hostname.in_([item.hostname for item in preview.devices])),
            )))
            existing = list(result.scalars())
            for item in preview.devices:
                own = next((device for device in existing if device.hostname == item.hostname
                            and device.topology_id == topology_id), None)
                port = item.ssh_port or (own.ssh_port if own else 22) or 22
                for device in existing:
                    if (device.mgmt_ip, device.ssh_port or 22) == (item.mgmt_ip, port) and device is not own:
                        preview.issues.append(ImportIssue(
                            code="database_ip_conflict",
                            message=f"管理地址与SSH端口已被其他设备使用: {item.mgmt_ip}:{port}",
                        ))
        preview.current_device_count = (await db.execute(
            select(func.count(Device.id)).where(Device.topology_id == topology_id)
        )).scalar_one()
        preview.current_link_count = (await db.execute(
            select(func.count(TopologyLink.id)).where(TopologyLink.topology_id == topology_id)
        )).scalar_one()
        preview.replaced_link_count = (await db.execute(
            select(func.count(TopologyLink.id)).where(
                TopologyLink.topology_id == topology_id,
                TopologyLink.source_type == "baseline",
                TopologyLink.link_type != "management",
            )
        )).scalar_one()
        if inventory_only:
            try:
                await TopologyBaselineService._require_inventory_without_links(db, topology_id)
            except ValueError as exc:
                preview.issues.append(ImportIssue(code="inventory_existing_links", message=str(exc)))
        preview.is_valid = not preview.issues
        return preview

    @staticmethod
    async def _require_inventory_without_links(db: AsyncSession, topology_id: int) -> None:
        # Current reads are also used during import after taking the topology lock;
        # a prior auth/preview transaction snapshot cannot authorize stale emptiness.
        links = (await db.execute(select(TopologyLink.id).where(
            TopologyLink.topology_id == topology_id).with_for_update())).scalars().all()
        if links:
            raise ValueError("当前拓扑已有链路，不能使用仅设备库存模式")
        versions = (await db.execute(select(TopologyVersion.snapshot_json).where(
            TopologyVersion.topology_id == topology_id).with_for_update())).scalars().all()
        for raw in versions:
            try:
                snapshot = json.loads(raw)
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("links"), list):
                    raise ValueError
            except (ValueError, TypeError):
                raise ValueError("历史链路基线无法核验，不能使用仅设备库存模式") from None
            if snapshot["links"]:
                raise ValueError("已有历史链路基线，不能使用仅设备库存模式")

    @staticmethod
    async def _snapshot(db: AsyncSession, topology_id: int, *, for_update: bool = False) -> dict:
        device_query = select(Device).where(Device.topology_id == topology_id).order_by(Device.hostname)
        link_query = select(TopologyLink).where(TopologyLink.topology_id == topology_id).order_by(TopologyLink.id)
        if for_update:
            # MySQL current reads must not reuse an earlier request/auth snapshot.
            device_query = device_query.with_for_update()
            link_query = link_query.with_for_update()
        devices = list((await db.execute(
            device_query.execution_options(populate_existing=True)
        )).scalars())
        links = list((await db.execute(
            link_query.execution_options(populate_existing=True)
        )).scalars())
        names = {device.id: device.hostname for device in devices}
        return {
            "devices": [
                {
                    "id": device.id,
                    "hostname": device.hostname,
                    "mgmt_ip": device.mgmt_ip,
                    "ssh_port": device.ssh_port,
                    "device_type": device.device_type.value,
                    "vendor": device.vendor.value,
                    "network_role": device.network_role,
                    "notes": device.notes,
                }
                for device in devices
            ],
            "links": [
                {
                    "source_device": names[link.source_device_id],
                    "source_interface": link.source_interface,
                    "target_device": names[link.target_device_id],
                    "target_interface": link.target_interface,
                    "source_ip": link.source_ip,
                    "target_ip": link.target_ip,
                    "link_type": link.link_type,
                    "status": link.status,
                    "discovery_source": link.discovery_source,
                    "source_type": link.source_type,
                }
                for link in links
                if link.source_device_id in names and link.target_device_id in names
            ],
        }

    @staticmethod
    async def fingerprint(db: AsyncSession, topology_id: int, *, for_update: bool = False) -> str:
        """Hash comparison inputs, excluding secrets and transient device online state."""
        snapshot = await TopologyBaselineService._snapshot(db, topology_id, for_update=for_update)
        canonical = {
            key: sorted(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        for item in items)
            for key, items in snapshot.items()
        }
        return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()

    @staticmethod
    async def _latest_version(db: AsyncSession, topology_id: int, *, for_update: bool = False) -> TopologyVersion | None:
        query = (select(TopologyVersion)
            .where(TopologyVersion.topology_id == topology_id)
            .order_by(TopologyVersion.version.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update()
        return (await db.execute(query)).scalar_one_or_none()

    @staticmethod
    async def _has_dependent_rows(db: AsyncSession, device_id: int) -> bool:
        """设备是否已被历史数据引用（决定回滚时能否硬删）。"""
        from modules.device.service import DeviceService
        return bool(await DeviceService.device_dependencies(db, device_id))

    @staticmethod
    async def _restore_snapshot(db: AsyncSession, topology_id: int, snapshot: dict) -> None:
        existing = list((await db.execute(
            select(Device).where(Device.topology_id == topology_id)
        )).scalars())
        snapshot_names = {item["hostname"] for item in snapshot["devices"]}
        await db.execute(delete(TopologyLink).where(TopologyLink.topology_id == topology_id))
        for device in existing:
            if device.hostname in snapshot_names:
                continue
            # 有历史数据的设备不能硬删（config_version/deploy_task/metric_record/alarm 等
            # 都是 nullable=False 的外键，MySQL 会直接 IntegrityError）；
            # 这类设备保留在库里并标记离线，避免回滚把历史记录一起毁掉。
            if await TopologyBaselineService._has_dependent_rows(db, device.id):
                device.status = DeviceStatus.OFFLINE
                logger.warning("topology_rollback_device_retained", device_id=device.id, hostname=device.hostname)
                continue
            await db.delete(device)
        devices = {device.hostname: device for device in existing if device.hostname in snapshot_names}
        for item in snapshot["devices"]:
            device = devices.get(item["hostname"])
            if device is None:
                device = Device(
                    hostname=item["hostname"],
                    mgmt_ip=item["mgmt_ip"],
                    topology_id=topology_id,
                    device_type=DeviceType(item["device_type"]),
                    vendor=DeviceVendor(item["vendor"]),
                    status=DeviceStatus.UNKNOWN,
                )
                db.add(device)
                devices[device.hostname] = device
            device.mgmt_ip = item["mgmt_ip"]
            device.ssh_port = item.get("ssh_port", 22)
            device.device_type = DeviceType(item["device_type"])
            device.vendor = DeviceVendor(item["vendor"])
            device.network_role = item.get("network_role") or "access"
            device.notes = item.get("notes")
        await db.flush()

        for item in snapshot["links"]:
            source = devices.get(item["source_device"])
            target = devices.get(item["target_device"])
            if not source or not target:
                continue
            db.add(TopologyLink(
                topology_id=topology_id,
                source_device_id=source.id,
                source_interface=item["source_interface"],
                target_device_id=target.id,
                target_interface=item["target_interface"],
                source_ip=item.get("source_ip"),
                target_ip=item.get("target_ip"),
                link_type=item.get("link_type") or "physical",
                status=item.get("status") or "up",
                discovery_source=item.get("discovery_source") or "excel",
                source_type=item.get("source_type") or "baseline",
            ))
        topology = await db.get(Topology, topology_id)
        topology.device_count = (await db.execute(
            select(func.count(Device.id)).where(Device.topology_id == topology_id)
        )).scalar_one()
        await db.flush()

    @staticmethod
    async def import_workbook(
        db: AsyncSession,
        topology_id: int,
        content: bytes,
        source_name: str,
        user_id: int,
        *, inventory_only: bool = False,
    ) -> dict:
        await db.execute(select(Topology).where(Topology.id == topology_id).with_for_update())
        preview = await TopologyBaselineService.preview(db, topology_id, content, inventory_only=inventory_only)
        if not preview.is_valid:
            raise ValueError("; ".join(issue.message for issue in preview.issues))

        latest = await TopologyBaselineService._latest_version(db, topology_id)
        previous = json.loads(latest.snapshot_json) if latest else await TopologyBaselineService._snapshot(db, topology_id)
        if latest is None and (previous["devices"] or previous["links"]):
            latest = TopologyVersion(
                topology_id=topology_id,
                version=1,
                batch_id=str(uuid4()),
                source_name="pre-import-baseline",
                source_type="pre_import",
                snapshot_json=json.dumps(previous, ensure_ascii=False, sort_keys=True),
                summary_json=json.dumps(snapshot_diff(None, previous), ensure_ascii=False, sort_keys=True),
                created_by=user_id,
            )
            db.add(latest)
            await db.flush()

        existing = list((await db.execute(
            select(Device).where(Device.topology_id == topology_id)
        )).scalars())
        devices = {device.hostname: device for device in existing}
        for item in preview.devices:
            device = devices.get(item.hostname)
            if device is None:
                device = Device(
                    hostname=item.hostname,
                    mgmt_ip=item.mgmt_ip,
                    topology_id=topology_id,
                    device_type=_device_type(item.hostname),
                    vendor=DeviceVendor.HUAWEI,
                    status=DeviceStatus.UNKNOWN,
                    network_role=_network_role(item.hostname),
                )
                db.add(device)
                devices[item.hostname] = device
            device.mgmt_ip = item.mgmt_ip
            # Legacy sheets omit the port; preserve existing mapped endpoints.
            if item.ssh_port is not None:
                device.ssh_port = item.ssh_port
            device.notes = item.notes
        await db.flush()

        if not inventory_only:
            await db.execute(delete(TopologyLink).where(
                TopologyLink.topology_id == topology_id,
                TopologyLink.source_type == "baseline",
                TopologyLink.link_type != "management",
            ))
        for item in preview.links:
            db.add(TopologyLink(
                topology_id=topology_id,
                source_device_id=devices[item.source_device].id,
                source_interface=item.source_interface,
                target_device_id=devices[item.target_device].id,
                target_interface=item.target_interface,
                source_ip=item.source_ip,
                target_ip=item.target_ip,
                link_type="physical",
                status="up",
                discovery_source="excel",
                source_type="baseline",
            ))
        topology = await db.get(Topology, topology_id)
        # 设备实体只增不删（有历史数据的保留），因此 device_count 必须按库内实际数量算，
        # 否则会与 Device 行数不一致，并破坏 confirm_runtime_baseline 的前置校验。
        actual_count = (await db.execute(
            select(func.count()).select_from(Device).where(Device.topology_id == topology_id)
        )).scalar() or 0
        topology.device_count = actual_count
        await db.flush()

        current = await TopologyBaselineService._snapshot(db, topology_id)
        diff = snapshot_diff(previous, current)
        version_number = (latest.version + 1) if latest else 1
        version = TopologyVersion(
            topology_id=topology_id,
            version=version_number,
            batch_id=str(uuid4()),
            source_name=Path(source_name).name[:255] or "baseline.xlsx",
            source_type="inventory_only" if inventory_only else "excel",
            snapshot_json=json.dumps(current, ensure_ascii=False, sort_keys=True),
            summary_json=json.dumps(diff, ensure_ascii=False, sort_keys=True),
            created_by=user_id,
        )
        db.add(version)
        await db.flush()
        return {
            "version": version_number,
            "batch_id": version.batch_id,
            "device_count": len(preview.devices),
            "link_count": len(preview.links),
            "source_type": version.source_type,
            "diff": diff,
        }

    @staticmethod
    async def confirm_runtime_baseline(
        db: AsyncSession,
        topology_id: int,
        runtime_check_id: int,
        user_id: int,
    ) -> dict:
        """Promote one complete, user-confirmed eNSP runtime check to the baseline."""
        await db.execute(select(Topology).where(Topology.id == topology_id).with_for_update())
        check = await db.get(TopologyRuntimeCheck, runtime_check_id)
        if not check or check.topology_id != topology_id:
            raise ValueError(f"运行态校验不存在: {runtime_check_id}")
        await db.refresh(check)
        if check.confirmed_version_id:
            raise ValueError("该运行态校验已固化为基线")
        if check.ssh_failed or not check.ssh_success:
            raise ValueError("运行态校验未完成，SSH必须全部成功后才能固化基线")
        if check.status == "partial" or json.loads(check.errors_json or "[]"):
            raise ValueError("运行态校验不完整，请处理邻居归属或采集诊断后重新校验，不能固化基线")

        latest = await TopologyBaselineService._latest_version(db, topology_id, for_update=True)
        if check.version_id != (latest.id if latest else None):
            raise ValueError("基线已变更，请重新运行校验后再固化")
        if not check.baseline_fingerprint:
            raise ValueError("历史校验缺少基线快照，请重新运行校验后再固化")
        if check.baseline_fingerprint != await TopologyBaselineService.fingerprint(db, topology_id, for_update=True):
            raise ValueError("基线已变更，请重新运行校验后再固化")
        devices = {
            device.hostname: device
            for device in (await db.execute(
                select(Device).where(Device.topology_id == topology_id)
            )).scalars()
        }
        if check.ssh_success != len(devices):
            raise ValueError("运行态校验设备数与当前拓扑不一致，不能固化基线")
        from modules.device.runtime_evidence import unpack_diff, evidence_fresh, VERSION
        from engines.device_adapter import get_device_mode
        _, coverage = unpack_diff(check.diff_json)
        if (not coverage or coverage.get('version') != VERSION
                or coverage.get('parsed_devices') != len(devices)
                or {s.get('device_id') for s in coverage.get('devices', [])} != {d.id for d in devices.values()}):
            raise ValueError('运行态校验缺少完整解析覆盖，请重新校验，不能固化历史未知证据')
        if not evidence_fresh(coverage) or coverage.get('mode') != get_device_mode():
            raise ValueError('运行态观察已过期或执行模式已改变，请重新校验后再固化')
        observed_links = json.loads(check.observed_links_json)
        if not observed_links:
            raise ValueError("运行态校验没有可确认的链路")
        for link in observed_links:
            if link.get("source_device") not in devices or link.get("target_device") not in devices:
                raise ValueError("运行态校验包含当前拓扑未知设备")

        previous = json.loads(latest.snapshot_json) if latest else await TopologyBaselineService._snapshot(db, topology_id)
        if latest is None:
            previous_version = TopologyVersion(
                topology_id=topology_id,
                version=1,
                batch_id=str(uuid4()),
                source_name="pre-runtime-confirmation",
                source_type="pre_runtime_confirmation",
                snapshot_json=json.dumps(previous, ensure_ascii=False, sort_keys=True),
                summary_json=json.dumps(snapshot_diff(None, previous), ensure_ascii=False, sort_keys=True),
                created_by=user_id,
            )
            db.add(previous_version)
            await db.flush()
            latest = previous_version

        await db.execute(delete(TopologyLink).where(
            TopologyLink.topology_id == topology_id,
            TopologyLink.source_type == "baseline",
        ))
        for link in observed_links:
            db.add(TopologyLink(
                topology_id=topology_id,
                source_device_id=devices[link["source_device"]].id,
                source_interface=link["source_interface"],
                target_device_id=devices[link["target_device"]].id,
                target_interface=link["target_interface"],
                source_ip=link.get("source_ip"),
                target_ip=link.get("target_ip"),
                link_type=link.get("link_type") or "physical",
                status="up",
                discovery_source="lldp",
                source_type="baseline",
            ))
        await db.flush()

        current = await TopologyBaselineService._snapshot(db, topology_id)
        version = TopologyVersion(
            topology_id=topology_id,
            version=latest.version + 1,
            batch_id=str(uuid4()),
            source_name=f"lldp-runtime-check-{check.id}",
            source_type="lldp",
            snapshot_json=json.dumps(current, ensure_ascii=False, sort_keys=True),
            summary_json=json.dumps(snapshot_diff(previous, current), ensure_ascii=False, sort_keys=True),
            created_by=user_id,
        )
        db.add(version)
        await db.flush()
        check.confirmed_version_id = version.id
        return {
            "version": version.version,
            "runtime_check_id": check.id,
            "device_count": len(devices),
            "link_count": len(observed_links),
            "diff": snapshot_diff(previous, current),
        }

    @staticmethod
    async def list_versions(db: AsyncSession, topology_id: int) -> list[dict]:
        versions = list((await db.execute(
            select(TopologyVersion)
            .where(TopologyVersion.topology_id == topology_id)
            .order_by(TopologyVersion.version.desc())
        )).scalars())
        version_by_id = {item.id: item.version for item in versions}
        return [
            {
                "id": item.id,
                "version": item.version,
                "batch_id": item.batch_id,
                "source_name": item.source_name,
                "source_type": item.source_type,
                "summary": json.loads(item.summary_json or "{}"),
                "rollback_of_version": version_by_id.get(item.rollback_of_id),
                "created_at": item.created_at,
            }
            for item in versions
        ]

    @staticmethod
    async def diff_version(db: AsyncSession, topology_id: int, version_number: int) -> dict:
        version = (await db.execute(select(TopologyVersion).where(
            TopologyVersion.topology_id == topology_id,
            TopologyVersion.version == version_number,
        ))).scalar_one_or_none()
        if not version:
            raise ValueError(f"拓扑版本不存在: {version_number}")
        current = await TopologyBaselineService._snapshot(db, topology_id)
        return snapshot_diff(json.loads(version.snapshot_json), current)

    @staticmethod
    async def rollback(
        db: AsyncSession,
        topology_id: int,
        version_number: int,
        user_id: int,
    ) -> dict:
        target = (await db.execute(select(TopologyVersion).where(
            TopologyVersion.topology_id == topology_id,
            TopologyVersion.version == version_number,
        ))).scalar_one_or_none()
        if not target:
            raise ValueError(f"拓扑版本不存在: {version_number}")
        await db.execute(select(Topology).where(Topology.id == topology_id).with_for_update())
        latest = await TopologyBaselineService._latest_version(db, topology_id)
        snapshot = json.loads(target.snapshot_json)
        await TopologyBaselineService._restore_snapshot(db, topology_id, snapshot)
        restored = await TopologyBaselineService._snapshot(db, topology_id)
        if any(snapshot_diff(snapshot, restored).values()):
            raise ValueError("拓扑回滚结果与目标版本不一致")
        diff = snapshot_diff(json.loads(latest.snapshot_json) if latest else None, restored)
        new_version_number = (latest.version + 1) if latest else 1
        version = TopologyVersion(
            topology_id=topology_id,
            version=new_version_number,
            batch_id=str(uuid4()),
            source_name=f"rollback-v{version_number}",
            source_type="rollback",
            snapshot_json=json.dumps(restored, ensure_ascii=False, sort_keys=True),
            summary_json=json.dumps(diff, ensure_ascii=False, sort_keys=True),
            created_by=user_id,
            rollback_of_id=target.id,
        )
        db.add(version)
        await db.flush()
        return {
            "version": new_version_number,
            "rollback_of_version": version_number,
            "diff": diff,
        }
