"""设备管理模块服务"""
import asyncio
import json
import socket
from datetime import datetime, timezone
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from core.security import credential_encryptor
from core.config import get_settings
from core.logger import get_logger
from modules.device.models import Device, Topology, TopologyLink, TopologyRuntimeCheck, TopologyVersion, DeviceStatus, validate_status_transition
from modules.system.service import SystemService

logger = get_logger("topology")


def _ssh_check_sync(ip: str, port: int, username: str, password: str, timeout: int = 8) -> bool:
    """同步SSH健康检查 - 支持keyboard-interactive和password两种认证"""
    import paramiko
    from engines.netmiko_exec import new_ssh_client
    client = new_ssh_client()
    try:
        # 先尝试普通password认证
        try:
            client.connect(hostname=ip, port=port, username=username, password=password,
                           timeout=timeout, allow_agent=False, look_for_keys=False,
                           auth_timeout=timeout)
            return True
        except paramiko.AuthenticationException:
            pass

        # 回退：使用transport做keyboard-interactive认证
        sock = socket.create_connection((ip, port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.connect()
        try:
            def handler(title, instructions, prompt_list):
                return [password] * len(prompt_list)
            transport.auth_interactive(username, handler)
            if transport.is_authenticated():
                return True
        finally:
            transport.close()
        return False
    except Exception as e:
        logger.debug("ssh_check_failed", ip=ip, error=str(e))
        return False
    finally:
        client.close()


class DeviceService:
    @staticmethod
    async def lock_topology(db: AsyncSession, topology_id: int | None) -> None:
        # Serialize inventory edits with import/rollback/runtime confirmation.
        if topology_id is not None:
            await db.execute(select(Topology.id).where(Topology.id == topology_id).with_for_update())

    @staticmethod
    async def create_device(db: AsyncSession, data: dict) -> Device:
        await DeviceService.lock_topology(db, data.get("topology_id"))
        device = Device(**data, status=DeviceStatus.UNKNOWN)
        db.add(device)
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def get_device(db: AsyncSession, device_id: int) -> Device:
        device = await db.get(Device, device_id)
        if not device:
            raise ValueError(f"设备不存在: {device_id}")
        return device

    @staticmethod
    async def get_devices_by_topology(db: AsyncSession, topology_id: int, status: DeviceStatus = None) -> list:
        query = select(Device).where(Device.topology_id == topology_id)
        if status:
            query = query.where(Device.status == status)
        result = await db.execute(query)
        return list(result.scalars().all())

    _UPDATABLE_FIELDS = {"hostname", "mgmt_ip", "ssh_port", "device_type", "vendor", "model", "vrp_version", "network_role", "notes", "tags"}

    @staticmethod
    async def update_device(db: AsyncSession, device_id: int, data: dict) -> Device:
        device = await DeviceService.get_device(db, device_id)
        await DeviceService.lock_topology(db, device.topology_id)
        await db.refresh(device)
        for key, value in data.items():
            if value is not None and key in DeviceService._UPDATABLE_FIELDS:
                setattr(device, key, value)
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def delete_device(db: AsyncSession, device_id: int):
        from core.exceptions import AppException

        device = await DeviceService.get_device(db, device_id)
        topology_id = device.topology_id
        await DeviceService.lock_topology(db, topology_id)
        # Include every registered FK (links have two endpoints, counted once).
        # Reject instead of silently cascading away monitoring/deployment history.
        dependencies = await DeviceService.device_dependencies(db, device_id)
        if dependencies:
            raise AppException(
                "设备存在关联链路或历史记录，不能删除；请先核对引用，历史记录将保留。",
                status_code=409, detail={"dependencies": dependencies},
            )
        try:
            await db.delete(device)
            await db.flush()
            topology = await db.get(Topology, topology_id)
            if topology:
                topology.device_count = await db.scalar(
                    select(func.count()).select_from(Device).where(Device.topology_id == topology_id)
                ) or 0
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise AppException("设备出现新的关联记录，删除已取消，请刷新后核对引用。", status_code=409) from exc

    @staticmethod
    async def device_dependencies(db: AsyncSession, device_id: int) -> dict[str, int]:
        dependencies = {}
        for table in Device.metadata.tables.values():
            columns = [fk.parent for fk in table.foreign_keys if fk.target_fullname == "device.id"]
            if columns:
                count = await db.scalar(select(func.count()).select_from(table).where(
                    or_(*(column == device_id for column in columns))
                ))
                if count:
                    dependencies[table.name] = count
        return dependencies

    @staticmethod
    async def update_device_status(db: AsyncSession, device_id: int, new_status: DeviceStatus) -> Device:
        device = await DeviceService.get_device(db, device_id)
        if not validate_status_transition(device.status, new_status):
            raise ValueError(f"非法状态流转: {device.status.value} -> {new_status.value}")
        device.status = new_status
        device.status_changed_at = datetime.now(timezone.utc)
        if new_status == DeviceStatus.ONLINE:
            device.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(device)
        return device

    @staticmethod
    async def get_device_credentials(device: Device) -> dict:
        settings = get_settings()
        if device.username_encrypted:
            return {
                "username": credential_encryptor.decrypt(device.username_encrypted),
                # password_encrypted 可能为 NULL（username 有值但密码没配），
                # 此前直接 decrypt(None) → None.encode() → AttributeError → 500
                "password": credential_encryptor.decrypt(device.password_encrypted) if device.password_encrypted else "",
                "enable": credential_encryptor.decrypt(device.enable_encrypted) if device.enable_encrypted else ""
            }
        return {
            "username": settings.device_default_username,
            "password": settings.device_default_password,
            "enable": settings.device_default_enable
        }

    @staticmethod
    async def check_device_health(db: AsyncSession, device_id: int, username: str = None, password: str = None) -> dict:
        """检查单台设备连通性并更新状态。

        ssh 模式：SSH 探测；sim 模式（DEVICE_MODE=sim）：无凭据也视为在线，
        用于无 eNSP 时跑通下发/采集/监控/训练全链路。
        """
        device = await DeviceService.get_device(db, device_id)

        from engines.device_adapter import get_device_mode
        if get_device_mode() == "sim":
            is_alive = True
        else:
            creds = await DeviceService.get_device_credentials(device)
            uname = username or creds["username"]
            pwd = password or creds["password"]
            if not uname or not pwd:
                return {"device_id": device_id, "hostname": device.hostname, "status": "unknown", "error": "无SSH凭证"}
            loop = asyncio.get_running_loop()
            settings = get_settings()
            is_alive = await loop.run_in_executor(None, _ssh_check_sync, device.mgmt_ip, device.ssh_port, uname, pwd, settings.ssh_connect_timeout)

        new_status = DeviceStatus.ONLINE if is_alive else DeviceStatus.OFFLINE
        old_status = device.status
        if old_status != new_status:
            device.status = new_status
            device.status_changed_at = datetime.now(timezone.utc)
            if new_status == DeviceStatus.ONLINE:
                device.last_seen_at = datetime.now(timezone.utc)
            await db.commit()

        logger.info("device_health_check", device_id=device_id, hostname=device.hostname, old=old_status.value, new=new_status.value)
        return {"device_id": device_id, "hostname": device.hostname, "status": new_status.value}

    @staticmethod
    async def check_all_devices_health(db: AsyncSession, topology_id: int = None, username: str = None, password: str = None) -> list:
        """批量真实探测设备 SSH 连通性并更新状态（并发探测、串行落库）。

        此前实现只读数据库状态不探测，设备上线/下线后状态永远不更新。
        """
        if topology_id:
            devices = await DeviceService.get_devices_by_topology(db, topology_id)
        else:
            result = await db.execute(select(Device))
            devices = list(result.scalars().all())
        if not devices:
            return []

        # sim 模式下不做 SSH 探测（无凭据也应视为在线），与单台版本语义保持一致：
        # 此前批量版会因缺凭据把全部设备刷成 OFFLINE，进而让下发被永久拒绝。
        from engines.device_adapter import get_device_mode
        if get_device_mode() == "sim":
            results: list[dict] = []
            now = datetime.now(timezone.utc)
            for device in devices:
                if device.status != DeviceStatus.ONLINE:
                    device.status = DeviceStatus.ONLINE
                    device.status_changed_at = now
                device.last_seen_at = now
                results.append({
                    "device_id": device.id,
                    "hostname": device.hostname,
                    "status": device.status.value,
                    "mode": "sim",
                })
            await db.commit()
            return results

        import asyncio
        loop = asyncio.get_running_loop()
        settings = get_settings()
        sem = asyncio.Semaphore(6)

        async def probe(device: Device) -> tuple[Device, bool]:
            creds = await DeviceService.get_device_credentials(device)
            uname = username or creds.get("username") or ""
            pwd = password or creds.get("password") or ""
            if not uname or not pwd:
                return device, False
            async with sem:
                try:
                    alive = await loop.run_in_executor(
                        None, _ssh_check_sync, device.mgmt_ip, device.ssh_port,
                        uname, pwd, settings.ssh_connect_timeout,
                    )
                except Exception:  # noqa: BLE001
                    alive = False
                return device, alive

        probed = await asyncio.gather(*(probe(d) for d in devices))
        # 串行更新状态与时间戳（共享请求 session 不能并发写）
        results: list[dict] = []
        now = datetime.now(timezone.utc)
        for device, alive in probed:
            new_status = DeviceStatus.ONLINE if alive else DeviceStatus.OFFLINE
            if device.status != new_status:
                device.status = new_status
                device.status_changed_at = now
            if alive:
                device.last_seen_at = now
            results.append({
                "device_id": device.id,
                "hostname": device.hostname,
                "status": device.status.value,
                "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            })
        await db.commit()
        return results


class TopologyService:
    @staticmethod
    def _layout_key(topology_id: int, kind: str) -> str:
        return f"topology:{topology_id}:layout:{kind}"

    @staticmethod
    def _read_layout_positions(value: str | None, device_ids: set[int]) -> dict[str, dict[str, float]]:
        try:
            positions = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(positions, dict):
            return {}
        return {
            str(device_id): {"x": position["x"], "y": position["y"]}
            for key, position in positions.items()
            if str(key).isdigit()
            and (device_id := int(key)) in device_ids
            and isinstance(position, dict)
            and isinstance(position.get("x"), (int, float))
            and isinstance(position.get("y"), (int, float))
            and 0 <= position["x"] <= 1
            and 0 <= position["y"] <= 1
        }

    @staticmethod
    async def get_layout(db: AsyncSession, topology_id: int) -> dict:
        await TopologyService.get_topology(db, topology_id)
        devices = await DeviceService.get_devices_by_topology(db, topology_id)
        device_ids = {device.id for device in devices}
        keys = [TopologyService._layout_key(topology_id, kind) for kind in ("draft", "published")]
        from modules.system.models import SystemConfig
        configs = (await db.execute(select(SystemConfig).where(SystemConfig.config_key.in_(keys)))).scalars().all()
        values = {config.config_key: config.config_value for config in configs}
        return {
            "draft_positions": TopologyService._read_layout_positions(values.get(keys[0]), device_ids),
            "published_positions": TopologyService._read_layout_positions(values.get(keys[1]), device_ids),
        }

    @staticmethod
    async def save_layout_draft(db: AsyncSession, topology_id: int, positions: dict[int, dict], username: str) -> dict:
        await TopologyService.get_topology(db, topology_id)
        device_ids = {device.id for device in await DeviceService.get_devices_by_topology(db, topology_id)}
        if not set(positions).issubset(device_ids):
            raise ValueError("布局包含不属于该拓扑的设备")
        serialized = {str(device_id): {"x": position.x, "y": position.y} for device_id, position in positions.items()}
        await SystemService.set_config(
            db,
            TopologyService._layout_key(topology_id, "draft"),
            json.dumps(serialized),
            "拓扑布局草稿",
            username,
        )
        return await TopologyService.get_layout(db, topology_id)

    @staticmethod
    async def publish_layout(db: AsyncSession, topology_id: int, username: str) -> dict:
        await TopologyService.get_topology(db, topology_id)
        from modules.system.models import SystemConfig
        draft = (await db.execute(select(SystemConfig).where(
            SystemConfig.config_key == TopologyService._layout_key(topology_id, "draft")
        ))).scalar_one_or_none()
        if draft is None:
            raise ValueError("没有可发布的布局草稿")
        await SystemService.set_config(
            db,
            TopologyService._layout_key(topology_id, "published"),
            draft.config_value,
            "已发布拓扑布局",
            username,
        )
        return await TopologyService.get_layout(db, topology_id)

    @staticmethod
    async def discover_via_lldp(db: AsyncSession, topology_id: int) -> dict:
        """Collect LLDP runtime state and record differences without changing baseline links."""
        from modules.device.topology_import import compare_topology_links
        from modules.device.baseline_service import TopologyBaselineService

        devices = await DeviceService.get_devices_by_topology(db, topology_id)
        if not devices:
            from core.exceptions import AppException
            raise AppException("拓扑下无设备，请先导入基线或添加设备后再校验。", status_code=422)

        names = {device.id: device.hostname for device in devices}
        all_links = await TopologyService.get_links(db, topology_id)
        baseline_links = [
            {
                "source_device": names[link.source_device_id],
                "source_interface": link.source_interface,
                "target_device": names[link.target_device_id],
                "target_interface": link.target_interface,
                "source_ip": link.source_ip,
                "target_ip": link.target_ip,
            }
            for link in all_links
            if link.source_type == "baseline"
            and link.source_device_id in names
            and link.target_device_id in names
        ]
        latest_version = (await db.execute(
            select(TopologyVersion)
            .where(TopologyVersion.topology_id == topology_id)
            .order_by(TopologyVersion.version.desc())
            .limit(1)
        )).scalar_one_or_none()
        # Capture the compared baseline before network I/O; a later version must
        # invalidate this evidence rather than being labelled as its comparison.
        compared_version_id = latest_version.id if latest_version else None
        baseline_fingerprint = await TopologyBaselineService.fingerprint(db, topology_id)
        collected = await TopologyService._collect_lldp_observations(devices)
        # End the read transaction so MySQL repeatable-read can see changes made
        # while collection was waiting on devices.
        await db.commit()
        diff = compare_topology_links(baseline_links, collected["observed_links"])
        diff_data = diff.model_dump()
        from modules.device.runtime_evidence import build_coverage, evidence_fresh
        from engines.device_adapter import get_device_mode
        samples = collected.get('coverage_samples')
        coverage = build_coverage(samples, baseline_count=len(baseline_links),
                                  manual_count=sum(link.source_type != 'baseline' for link in all_links),
                                  mode=collected.get('mode', 'unknown')) if samples is not None else None
        incomplete = (collected['ssh_failed'] or collected['errors'] or coverage is None
                      or coverage['parsed_devices'] != len(devices) or not evidence_fresh(coverage)
                      or coverage['mode'] != get_device_mode())
        status = ('partial' if incomplete else 'no_baseline' if not baseline_links
                  else 'different' if diff.has_differences else 'matched')
        check = TopologyRuntimeCheck(
            topology_id=topology_id,
            version_id=compared_version_id,
            baseline_fingerprint=baseline_fingerprint,
            status=status,
            ssh_success=collected["ssh_success"],
            ssh_failed=collected["ssh_failed"],
            observed_links_json=json.dumps(collected["observed_links"], ensure_ascii=False),
            diff_json=json.dumps(diff_data | {'_coverage': coverage}, ensure_ascii=False),
            errors_json=json.dumps(collected["errors"], ensure_ascii=False),
        )
        db.add(check)
        await db.commit()
        current_version = await TopologyBaselineService._latest_version(db, topology_id)
        current_version_id = current_version.id if current_version else None
        is_stale = (compared_version_id != current_version_id or
                    baseline_fingerprint != await TopologyBaselineService.fingerprint(db, topology_id))
        logger.info(
            "lldp_runtime_check_complete",
            topology_id=topology_id,
            status=status,
            observed=len(collected["observed_links"]),
        )
        return {
            "check_id": check.id,
            "status": status,
            "discovered": len(collected["observed_links"]),
            "imported": 0,
            "ssh_success": collected["ssh_success"],
            "ssh_failed": collected["ssh_failed"],
            "links": collected["observed_links"],
            "diff": diff_data,
            "coverage": coverage,
            "evidence_stale": not evidence_fresh(coverage),
            "mode_changed": bool(coverage and coverage['mode'] != get_device_mode()),
            "errors": collected["errors"],
            "compared_version_id": check.version_id,
            "confirmed_version_id": None,
            "current_version_id": current_version_id,
            "is_stale": is_stale,
            "created_at": check.created_at,
        }

    @staticmethod
    async def _collect_lldp_observations(devices: list) -> dict:
        from engines.device_adapter import get_device_adapter
        from modules.device.lldp_parser import build_neighbor_pairs
        from modules.device.runtime_evidence import analyze_lldp_output
        from engines.device_adapter import get_device_mode
        from modules.device.readonly_commands import get_readonly_commands

        settings = get_settings()
        semaphore = asyncio.Semaphore(settings.topology_concurrent_ssh)
        known_hostnames = {device.hostname for device in devices}
        mode = get_device_mode()

        async def collect(device):
            async with semaphore:
                neighbors = [d.hostname for d in devices if d.hostname != device.hostname]
                adapter = None
                # next() 必须带默认值：命令集被调整时抛 StopIteration 会在协程里
                # 变成 RuntimeError 并被下面的 except 吞成一条错误字符串
                command = next(
                    (item for item in get_readonly_commands(device.device_type.value, device.model)
                     if "lldp neighbor" in item),
                    "display lldp neighbor brief",
                )
                try:
                    adapter = await get_device_adapter(device, neighbors=neighbors)
                    output = await adapter.run_command(command)
                    return device, output, None, datetime.now(timezone.utc).isoformat(), getattr(adapter, 'name', mode)
                except Exception as exc:
                    return device, "", str(exc), datetime.now(timezone.utc).isoformat(), mode
                finally:
                    if adapter is not None:
                        await adapter.close()

        results = await asyncio.gather(*(collect(device) for device in devices))
        neighbors = {}
        errors = []
        ssh_success = 0
        samples = []
        observed_modes = set()
        for device, output, error, observed_at, adapter_mode in results:
            hostname = device.hostname
            observed_modes.add(adapter_mode)
            sample = {'device_id': device.id, 'hostname': hostname, 'observed_at': observed_at,
                      'ssh_ok': not bool(error), 'state': 'failed', 'complete': False, 'neighbors': []}
            samples.append(sample)
            if error:
                errors.append(f"{hostname}: {error}")
                continue
            ssh_success += 1
            parsed_result = analyze_lldp_output(output)
            sample.update({k: parsed_result[k] for k in ('state', 'complete', 'neighbors')})
            parsed = parsed_result['neighbors']
            if not parsed_result['complete']:
                errors.append(f"{hostname}: {parsed_result['message']}")
            unresolved = [neighbor for neighbor in parsed if neighbor["neighbor_device"] not in known_hostnames]
            if unresolved:
                # Keep the graph restricted to known identities, but never let
                # discarded observations turn an incomplete check into a match.
                details = "；".join(
                    f'{item["local_interface"][:128]} → {item["neighbor_device"][:128]}/{item["remote_interface"][:128]}'
                    for item in unresolved[:5]
                )
                if len(unresolved) > 5:
                    details += f"；另有 {len(unresolved) - 5} 条"
                errors.append(
                    f"{hostname}: {len(unresolved)} 条 LLDP 邻居无法归属当前拓扑库存（{details}），"
                    "未计入运行态链路；请核对库存设备名与邻居标识。"
                )
            resolved = [
                neighbor for neighbor in parsed
                if neighbor["neighbor_device"] in known_hostnames
            ]
            if resolved:
                neighbors[hostname] = resolved
        observed_links = [
            {
                "source_device": link["src_dev"],
                "source_interface": link["src_if"],
                "target_device": link["dst_dev"],
                "target_interface": link["dst_if"],
                "source_ip": None,
                "target_ip": None,
                "link_type": link["link_type"],
            }
            for link in build_neighbor_pairs(neighbors)
        ]
        return {
            "observed_links": observed_links,
            "ssh_success": ssh_success,
            "ssh_failed": len(devices) - ssh_success,
            "errors": errors,
            "coverage_samples": samples,
            "mode": mode if observed_modes == {mode} else 'mixed',
        }

    @staticmethod
    async def get_latest_runtime_check(db: AsyncSession, topology_id: int) -> dict | None:
        from modules.device.baseline_service import TopologyBaselineService
        check = (await db.execute(
            select(TopologyRuntimeCheck)
            .where(TopologyRuntimeCheck.topology_id == topology_id)
            .order_by(TopologyRuntimeCheck.created_at.desc(), TopologyRuntimeCheck.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        if not check:
            return None
        current_version_id = (await db.execute(
            select(TopologyVersion.id).where(TopologyVersion.topology_id == topology_id)
            .order_by(TopologyVersion.version.desc()).limit(1)
        )).scalar_one_or_none()
        errors = json.loads(check.errors_json or "[]")
        from modules.device.runtime_evidence import unpack_diff, evidence_fresh
        from engines.device_adapter import get_device_mode
        diff, coverage = unpack_diff(check.diff_json)
        return {
            "check_id": check.id,
            "status": check.status,
            "ssh_success": check.ssh_success,
            "ssh_failed": check.ssh_failed,
            "links": json.loads(check.observed_links_json),
            "discovered": len(json.loads(check.observed_links_json)),
            "diff": diff,
            "coverage": coverage,
            "evidence_stale": not evidence_fresh(coverage),
            "mode_changed": bool(coverage and coverage['mode'] != get_device_mode()),
            "errors": errors if isinstance(errors, list) else [json.dumps(errors, ensure_ascii=False, sort_keys=True)],
            "created_at": check.created_at,
            "compared_version_id": check.version_id,
            "confirmed_version_id": check.confirmed_version_id,
            "current_version_id": current_version_id,
            "is_stale": (check.version_id != current_version_id or not check.baseline_fingerprint or
                         check.baseline_fingerprint != await TopologyBaselineService.fingerprint(db, topology_id)),
        }

    @staticmethod
    async def create_topology(db: AsyncSession, data: dict) -> Topology:
        # owner_id 此前建模后从未写入（死字段）：这里记下创建者，便于后续归属判断
        payload = dict(data)
        payload.setdefault("owner_id", None)
        topology = Topology(**payload)
        db.add(topology)
        await db.commit()
        await db.refresh(topology)
        return topology

    @staticmethod
    async def get_topology(db: AsyncSession, topology_id: int) -> Topology:
        topology = await db.get(Topology, topology_id)
        if not topology:
            raise ValueError(f"拓扑不存在: {topology_id}")
        return topology

    @staticmethod
    async def list_topologies(db: AsyncSession) -> list:
        result = await db.execute(select(Topology).where(Topology.status == "active"))
        return list(result.scalars().all())

    @staticmethod
    async def add_link(db: AsyncSession, topology_id: int, source_id: int, source_if: str, target_id: int, target_if: str, discovery_source: str = "manual") -> TopologyLink:
        await DeviceService.lock_topology(db, topology_id)
        link = TopologyLink(topology_id=topology_id, source_device_id=source_id, source_interface=source_if, target_device_id=target_id, target_interface=target_if, discovery_source=discovery_source)
        db.add(link)
        await db.commit()
        await db.refresh(link)
        return link

    @staticmethod
    async def get_links(db: AsyncSession, topology_id: int) -> list:
        result = await db.execute(select(TopologyLink).where(TopologyLink.topology_id == topology_id))
        return list(result.scalars().all())
