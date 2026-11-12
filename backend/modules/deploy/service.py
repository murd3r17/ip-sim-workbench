"""配置下发服务"""
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from core.config import get_settings
from core.logger import get_logger
from modules.deploy.models import DeployBatch, DeployTask, DeployStatus, ChangeLevel, ConfigTemplate, ConfigVersion, DeviceWriteLock
from modules.auth.service import AuditService
from modules.deploy.vrp_validator import RiskLevel, VRPValidator
from modules.deploy.config_verifier import ConfigVerifier, UnsupportedRestoreError
from modules.device.models import Device, DeviceStatus, TopologyVersion
from modules.device.service import DeviceService

logger = get_logger("deploy")


class DeployService:
    @staticmethod
    async def _claim_task(db: AsyncSession, task: DeployTask, expected: DeployStatus, target: DeployStatus) -> None:
        """Claim in the database, never from an ORM identity-map snapshot.

        Commit before device I/O so cancellation, expiry cleanup and another
        request all see the active state. Verification retains an active lease
        even if its original confirmation deadline has elapsed.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        lock_query = select(DeviceWriteLock.device_id).where(
            DeviceWriteLock.device_id == task.device_id, DeviceWriteLock.task_id == task.id,
        )
        if expected == DeployStatus.CONFIRMED:
            lock_query = lock_query.where(or_(DeviceWriteLock.expire_at.is_(None), DeviceWriteLock.expire_at > now))
        else:
            # DEPLOYING covers both active SSH and a finished execution awaiting
            # verification. The existing lease field distinguishes those phases.
            # 'deploy' is the legacy lease of executions completed before M1.
            lock_query = lock_query.where(DeviceWriteLock.lock_type.in_(("deploy", "deploy_ready", "deploy_simulated_ready")))
        values = {"status": target}
        if target == DeployStatus.DEPLOYING:
            values["started_at"] = now
        result = await db.execute(
            update(DeployTask).where(
                DeployTask.id == task.id, DeployTask.status == expected, exists(lock_query),
            ).values(**values).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await db.rollback()
            raise ValueError("任务状态已变化或设备写锁已失效，无法开始执行或验证")
        await db.execute(
            update(DeviceWriteLock).where(
                DeviceWriteLock.device_id == task.device_id, DeviceWriteLock.task_id == task.id,
            ).values(lock_type="deploy_executing" if target == DeployStatus.DEPLOYING else "deploy_verifying")
        )
        await db.commit()
        await db.refresh(task)

    @staticmethod
    async def _release_task_lock(db: AsyncSession, task: DeployTask) -> bool:
        result = await db.execute(
            delete(DeviceWriteLock).where(
                DeviceWriteLock.device_id == task.device_id, DeviceWriteLock.task_id == task.id,
            ).execution_options(synchronize_session="fetch")
        )
        return result.rowcount == 1

    @staticmethod
    async def capture_snapshots(db: AsyncSession, device_ids: list[int], operator_id: int) -> list[dict]:
        """只读采集运行配置并保存为快照。"""
        from engines.device_adapter import get_device_adapter
        snapshots = []
        for device_id in device_ids:
            device = await db.get(Device, device_id)
            if not device:
                raise ValueError(f"设备不存在: {device_id}")
            adapter = await get_device_adapter(device)
            try:
                config = await adapter.run_command("display current-configuration")
            finally:
                await adapter.close()
            version = ConfigVersion(
                device_id=device.id,
                version_number=await DeployService._next_version_number(db, device.id),
                config_snapshot=config,
                source="manual",
                change_description="manual running-config",
                created_by=operator_id,
            )
            db.add(version)
            await db.flush()
            snapshots.append({"device_id": device.id, "version_id": version.id, "source": version.source})
        await db.commit()
        return snapshots

    @staticmethod
    async def create_batch(
        db: AsyncSession,
        *,
        name: str,
        description: str | None,
        source: str,
        planned_at,
        items: list,
        engine: str,
        operator_id: int,
    ) -> dict:
        """创建具名父任务和每设备独立执行项，不连接或操作设备。"""
        devices: dict[int, Device] = {}
        validator = VRPValidator()
        for item in items:
            device = await db.get(Device, item.device_id)
            if not device:
                raise ValueError(f"设备不存在: {item.device_id}")
            if device.status != DeviceStatus.ONLINE:
                raise ValueError(f"设备 {device.hostname} 状态为 {device.status.value}，不允许下发")
            report = validator.assess(item.config_content, device.model or "unknown")
            if not report["valid"]:
                raise ValueError(f"设备 {device.hostname} 配置被阻断: {report['errors']}")
            devices[item.device_id] = device

        batch = DeployBatch(
            name=name, description=description, source=source, planned_at=planned_at, operator_id=operator_id,
        )
        db.add(batch)
        await db.flush()
        transaction_id = str(uuid.uuid4())[:12]
        results = []
        for item in items:
            task = DeployTask(
                batch_id=batch.id, transaction_id=transaction_id, device_id=item.device_id,
                config_content=item.config_content, template_id=item.template_id,
                status=DeployStatus.AWAITING_CONFIRMATION, engine=engine,
                change_level=(ChangeLevel.HIGH_RISK if validator.assess(
                    item.config_content, devices[item.device_id].model or "unknown"
                )["requires_confirmation"] else ChangeLevel.DAILY), operator_id=operator_id,
            )
            db.add(task)
            await db.flush()
            await AuditService.log(
                db, operator_id, "", "deploy", "deploy_task_created", "deploy_task", str(task.id),
                {"task_id": task.id, "device_id": task.device_id, "batch_id": batch.id, "result": "pending"},
            )
            results.append({
                "id": task.id, "device_id": task.device_id, "hostname": devices[task.device_id].hostname,
                "config_content": task.config_content, "status": task.status.value,
            })
        await db.commit()
        return {"id": batch.id, "name": batch.name, "source": batch.source, "items": results}

    @staticmethod
    def _device_in_snapshot(snapshot_json: str | None, device: Device) -> bool:
        """Require the complete ID/name/address/port identity in a usable baseline."""
        import json
        try:
            snapshot = json.loads(snapshot_json or "{}")
        except (TypeError, ValueError):
            logger.warning("deploy_allowlist_snapshot_unparsable", device_id=device.id)
            return False
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("devices"), list):
            return False
        entries = snapshot["devices"]
        if not all(isinstance(item, dict) for item in entries):
            return False
        # Legacy snapshots without IDs remain audit history, not execution authority.
        matches = [item for item in entries if item.get("id") == device.id]
        return len(matches) == 1 and all((
            matches[0].get("hostname") == device.hostname,
            matches[0].get("mgmt_ip") == device.mgmt_ip,
            type(matches[0].get("ssh_port")) is int,
            matches[0].get("ssh_port") == (device.ssh_port or 22),
        ))

    @staticmethod
    async def _is_authorized_stage4_target(db: AsyncSession, device: Device | None) -> bool:
        """真实设备动作只允许受控白名单内的设备。

        四道校验：设备 id、管理 IP、拓扑归属、基线版本快照。
        （此前 baseline 分支两条路径都 return True，等于只校验 id + IP，
         而三台设备共用同一个管理 IP，该维度实际不构成约束。）
        未指定基线、缺少基线或身份证据不完整时拒绝真实动作。
        """
        if not device:
            return False
        settings = get_settings()
        if not settings.deploy_allowlist_topology_id or not settings.deploy_allowlist_baseline_version:
            return False
        allow_ids = {
            int(x.strip())
            for x in settings.deploy_allowlist_device_ids.split(",")
            if x.strip().isdigit()
        }
        allow_ips = {
            x.strip()
            for x in settings.deploy_allowlist_mgmt_ips.split(",")
            if x.strip()
        }
        if device.id not in allow_ids or device.mgmt_ip not in allow_ips:
            return False
        if settings.deploy_allowlist_topology_id and device.topology_id != settings.deploy_allowlist_topology_id:
            return False
        if settings.deploy_allowlist_topology_id and settings.deploy_allowlist_baseline_version:
            baseline = (
                await db.execute(
                    select(TopologyVersion)
                    .where(
                        TopologyVersion.topology_id == settings.deploy_allowlist_topology_id,
                        TopologyVersion.version == settings.deploy_allowlist_baseline_version,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if baseline is None:
                logger.warning(
                    "deploy_allowlist_baseline_missing",
                    topology_id=settings.deploy_allowlist_topology_id,
                    version=settings.deploy_allowlist_baseline_version,
                )
                return False
            if not DeployService._device_in_snapshot(baseline.snapshot_json, device):
                logger.warning("deploy_allowlist_device_not_in_baseline", device_id=device.id)
                return False
        return True

    @staticmethod
    async def _assert_saved_matches_running(adapter, running: str) -> None:
        """Do not persist someone else's pre-existing unsaved changes."""
        saved = await adapter.run_command("display saved-configuration")
        if not running.strip() or not saved.strip():
            raise ValueError("未取得完整运行和启动配置，已拒绝保存")
        ConfigVerifier.raise_on_cli_error(running)
        ConfigVerifier.raise_on_cli_error(saved)
        if ConfigVerifier.verify_snapshot(running, saved) is not None:
            raise ValueError("运行配置与启动配置不一致，已拒绝隐式保存未授权变更")

    @staticmethod
    async def verify_task(db: AsyncSession, task_id: int, user: dict) -> dict:
        """4E：使用4D持久化回读完成差异、受控回滚和脱敏报告。"""
        task = await db.get(DeployTask, task_id)
        if not task:
            raise ValueError("任务状态不允许验证")
        if task.operator_id != user["user_id"] and user.get("role") != "admin":
            raise PermissionError("无权验证此任务")
        if task.status != DeployStatus.DEPLOYING:
            raise ValueError("任务状态不允许验证")
        lock = await db.get(DeviceWriteLock, task.device_id)
        if not lock or lock.task_id != task.id:
            raise ValueError("当前任务没有设备写锁")
        # A-07 / AF-02：模式只从执行记录或可靠历史证据判断，不读取当前开关。
        if task.execution_mode == "simulated":
            execution_mode = "simulated"
        elif task.execution_mode == "real":
            execution_mode = "real"
        elif lock.lock_type == "deploy_simulated_ready":
            execution_mode = "simulated"
        elif lock.lock_type == "deploy_ready":
            execution_mode = "real"
        else:
            execution_mode = "unknown"
        execution_simulated = execution_mode == "simulated"
        await DeployService._claim_task(db, task, DeployStatus.DEPLOYING, DeployStatus.VERIFYING)
        device = await db.get(Device, task.device_id)
        if not task.result_output:
            # 无回读有两种含义，必须区分，否则真实执行失败会被"洗白"成成功：
            #   1) 模拟执行本就不回读 → 成功
            #   2) 真实执行却没拿到回读 → 执行失败，判失败并释放写锁
            #   3) 历史模式未知 → 不能猜测成功，按失败处理并说明原因
            if execution_simulated:
                task.status = DeployStatus.SUCCESS
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await db.delete(lock)
                await db.commit()
                await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_verified", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "result": "no_readback"})
                await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "released"})
                return {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "verification": "not_performed", "result": "no_readback"}
            if execution_mode == "unknown":
                # 历史模式缺失：不能凭当前开关猜成模拟成功，也不能宣称真实失败。
                task.status = DeployStatus.FAILED
                task.error_message = "execution_mode_unknown"
                task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await db.delete(lock)
                await db.commit()
                await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_verified", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "mode": "unknown", "result": "no_readback"}, result="failed")
                await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "released"})
                return {
                    "task_id": task.id, "device_id": task.device_id, "mode": "unknown",
                    "verification": "failed", "result": "unknown_mode",
                    "note": "历史任务未记录执行模式，无法判断无回读属于模拟成功还是真实失败；按失败保留，请人工核对。",
                }
            task.status = DeployStatus.FAILED
            task.error_message = task.error_message or "no_readback"
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_verified", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "result": "no_readback"}, result="failed")
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "released"})
            return {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "verification": "failed", "result": "no_readback"}

        is_snapshot_restore = (task.config_watermark or "").startswith("rollback_from_version:")
        compare = ConfigVerifier.verify_snapshot if is_snapshot_restore else ConfigVerifier._compare_config
        diff = compare(task.config_content, task.result_output)
        if diff is None:
            task.verified = True
            task.status = DeployStatus.SUCCESS
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            task.verify_diff = None
            db.add(ConfigVersion(
                device_id=task.device_id,
                deploy_task_id=task.id,
                version_number=await DeployService._next_version_number(db, task.device_id),
                config_snapshot=task.result_output,
                change_description="4E verified running-config",
                created_by=user["user_id"],
            ))
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "success"})
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_verified", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "success"})
            return {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "verification": "passed", "result": "success"}

        task.verified = False
        task.verify_diff = diff
        if not task.backup_config:
            task.status = DeployStatus.FAILED
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            # 释放写锁：否则该设备会被残留锁永久卡住（confirm 持续 409、WebSSH 拒绝接入）
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_verified", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "result": "rollback_unavailable"}, result="failed")
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "released"})
            return {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "verification": "failed", "rollback": "unavailable"}
        if execution_simulated:
            task.status = DeployStatus.FAILED
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_verified", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "result": "rollback_required"}, result="failed")
            return {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "verification": "failed", "rollback": "required"}
        if not await DeployService._is_authorized_stage4_target(db, device):
            # 拒绝也要释放写锁，否则设备被永久锁死
            task.status = DeployStatus.FAILED
            task.error_message = "rollback_target_not_allowlisted"
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "released_not_allowlisted"}, result="failed")
            raise ValueError("设备不在受控回滚白名单")
        # 备份作为恢复目标；未知差异必须拒绝，不能盲目整机重放。
        forbidden = VRPValidator.check_rollback_safe(task.backup_config or "")
        if forbidden:
            task.status = DeployStatus.FAILED
            task.error_message = "rollback_blocked_destructive_command"
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(
                db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_rollback_blocked",
                "deploy_task", str(task.id),
                {"task_id": task.id, "device_id": task.device_id, "hits": forbidden[:3]},
                result="failed",
            )
            raise ValueError(f"回滚配置含破坏性命令，已拒绝执行: {forbidden[:3]}")
        from engines.device_adapter import get_device_adapter
        adapter = None
        try:
            adapter = await get_device_adapter(device)
            current = await adapter.run_command("display current-configuration")
            if not current.strip():
                raise ValueError("回滚前未取得设备配置，已拒绝写入")
            # Keep the observed state for a reviewed manual recovery if the
            # changed commands cannot be safely inverted.
            task.verify_diff = (task.verify_diff or "") + "\n恢复目标差异: " + (ConfigVerifier.verify_snapshot(task.backup_config, current) or "无差异")
            commands = ConfigVerifier.build_restore_commands(current, task.backup_config)
            await DeployService._assert_saved_matches_running(adapter, current)
            # 写入前先留痕（写操作前置审计，失败也能追溯意图）
            await AuditService.log(
                db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_rollback_started",
                "deploy_task", str(task.id),
                {"task_id": task.id, "device_id": task.device_id, "lines": len(commands)},
            )
            if commands:
                ConfigVerifier.raise_on_cli_error(await adapter.send_config(commands))
                ConfigVerifier.raise_on_cli_error(await adapter.save_config())
            task.rollback_output = await adapter.run_command("display current-configuration")
            rollback_diff = ConfigVerifier.verify_snapshot(task.backup_config, task.rollback_output)
            if not task.rollback_output.strip() or rollback_diff:
                task.verify_diff += "\n回滚核验: " + (rollback_diff or "未取得回读")
                raise ValueError("回滚后配置未恢复到备份状态")
            await DeployService._assert_saved_matches_running(adapter, task.rollback_output)
            task.status = DeployStatus.ROLLED_BACK
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "rolled_back"})
            result = "rolled_back"
        except Exception as exc:
            task.status = DeployStatus.FAILED
            task.error_message = type(exc).__name__
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "rollback_failed"}, result="failed")
            result = "rollback_unsupported" if isinstance(exc, UnsupportedRestoreError) else "rollback_failed"
        finally:
            if adapter is not None:
                await adapter.close()
        await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_rollback", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": result}, result="success" if result == "rolled_back" else "failed")
        return {"task_id": task.id, "device_id": task.device_id, "mode": execution_mode, "verification": "failed", "rollback": result}

    @staticmethod
    async def confirm_task(db: AsyncSession, task_id: int, user: dict, risk_confirm: bool) -> DeployTask:
        task = await db.get(DeployTask, task_id)
        if not task:
            raise ValueError("任务不存在")
        if task.status != DeployStatus.AWAITING_CONFIRMATION:
            raise ValueError("任务不处于待确认状态")
        if task.operator_id != user["user_id"] and user.get("role") != "admin":
            raise PermissionError("无权确认此任务")
        device = await db.get(Device, task.device_id)
        report = VRPValidator().assess(task.config_content, device.model or "unknown")
        requires_risk_confirm = report["requires_confirmation"] or task.change_level == ChangeLevel.HIGH_RISK
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        first_confirmation = task.confirmed_at is None
        confirmation_values = {}
        if first_confirmation:
            confirmation_values = {"confirmed_by": user["user_id"], "confirmed_at": now}
        if first_confirmation and requires_risk_confirm:
            result = await db.execute(
                update(DeployTask).where(
                    DeployTask.id == task.id, DeployTask.status == DeployStatus.AWAITING_CONFIRMATION,
                    DeployTask.confirmed_at.is_(None),
                ).values(**confirmation_values).execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                await db.rollback()
                raise ValueError("任务状态或确认记录已变化，请刷新后重试")
            await db.commit()
            await db.refresh(task)
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_confirmed", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "risk_level": "risk", "result": "awaiting_risk_confirmation"})
            raise ValueError("高风险任务需要二次确认")
        if requires_risk_confirm:
            if not risk_confirm:
                raise ValueError("高风险任务需要二次确认")
            confirmation_values.update(risk_confirmed_by=user["user_id"], risk_confirmed_at=now)
        device_id = task.device_id
        # BF-03：终端/训练/部署共用同一权威锁；终端先占时，确认必须在状态 CAS 前明确拒绝，
        # 不能靠后面的唯一键异常来“碰巧”拦截。
        existing_lock = await db.get(DeviceWriteLock, device_id)
        if existing_lock is not None:
            from core.exceptions import DeviceLockError
            raise DeviceLockError(str(device_id))
        try:
            result = await db.execute(
                update(DeployTask).where(
                    DeployTask.id == task.id, DeployTask.status == DeployStatus.AWAITING_CONFIRMATION,
                    (DeployTask.confirmed_at.is_(None) if first_confirmation else DeployTask.confirmed_at == task.confirmed_at),
                ).values(status=DeployStatus.CONFIRMED, **confirmation_values).execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                await db.rollback()
                raise ValueError("任务状态或确认记录已变化，请刷新后重试")
            db.add(DeviceWriteLock(
                device_id=device_id, task_id=task.id, lock_type="deploy",
                expire_at=DeployService._lock_expire_at(),
            ))
            await db.commit()
        except IntegrityError:
            await db.rollback()
            from core.exceptions import DeviceLockError
            raise DeviceLockError(str(device_id))
        await db.refresh(task)
        # 提交成功后才写审计，保证审计与事实一致
        await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "deploy_task_confirmed", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "risk_level": "risk" if requires_risk_confirm else "safe", "result": "confirmed"})
        return task

    @staticmethod
    def _lock_expire_at() -> datetime:
        """写锁过期时间 = 现在 + `deploy_lock_ttl_seconds`（设计 §15.3 的"过期时间"字段）。"""
        # getattr 兜底：单测里常用 SimpleNamespace 替换 settings，缺少新字段时不应让确认流程崩
        ttl = max(int(getattr(get_settings(), "deploy_lock_ttl_seconds", 3600)), 60)
        return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=ttl)

    @staticmethod
    async def cancel_task(db: AsyncSession, task_id: int, user: dict) -> dict:
        """取消未终结的下发任务并释放设备写锁。

        存在的理由：`confirm_task` 会为任务加 `DeviceWriteLock`，而释放只发生在
        `execute/verify` 的路径上。于是"确认了但没执行"（用户改主意、浏览器崩了、
        校验步骤失败）的任务会把设备**永久锁死** —— 终端拒绝接入、新任务 confirm 一直 409，
        而前后端都没有任何取消入口（2026-09-09 交付前实测被上一次 e2e 的
        confirmed 任务卡住就是这个问题）。
        """
        task = await db.get(DeployTask, task_id)
        if not task:
            raise ValueError("任务不存在")
        if task.operator_id != user["user_id"] and user.get("role") != "admin":
            raise PermissionError("无权限取消此任务")
        if task.status in (DeployStatus.SUCCESS, DeployStatus.FAILED,
                           DeployStatus.ROLLED_BACK, DeployStatus.CANCELLED):
            raise ValueError(f"任务已是终态（{task.status.value}），无法取消")
        result = await db.execute(
            update(DeployTask).where(
                DeployTask.id == task.id,
                DeployTask.status.in_((DeployStatus.PENDING, DeployStatus.AWAITING_CONFIRMATION, DeployStatus.CONFIRMED)),
            ).values(
                status=DeployStatus.CANCELLED, error_message="cancelled_by_user",
                completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ).execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            await db.rollback()
            raise ValueError("任务已进入执行或验证，不能取消或释放设备写锁")
        released = await DeployService._release_task_lock(db, task)
        await db.commit()
        await db.refresh(task)
        await AuditService.log(
            db, user["user_id"], user.get("username", ""), "deploy",
            "deploy_task_cancelled", "deploy_task", str(task.id),
            {"task_id": task.id, "device_id": task.device_id, "released_lock": released},
        )
        if released:
            await AuditService.log(
                db, user["user_id"], user.get("username", ""), "deploy",
                "device_write_lock_released", "deploy_task", str(task.id),
                {"task_id": task.id, "device_id": task.device_id, "result": "released_cancelled"},
            )
        return {"task_id": task.id, "status": task.status.value, "released_lock": released}

    # 可自动清理的锁：仅限"尚未进入执行"的任务。deploying/verifying 中的锁绝不自动释放
    # —— 那可能是正在合法执行的长任务，误放会导致同一设备被并发写（设计 §15.3 的"超时锁
    # 可自动释放"必须建立在"没有正在进行的写操作"之上）。
    _EXPIRABLE_TASK_STATUSES = (
        DeployStatus.PENDING,
        DeployStatus.AWAITING_CONFIRMATION,
        DeployStatus.CONFIRMED,
        DeployStatus.SUCCESS,
        DeployStatus.FAILED,
        DeployStatus.ROLLED_BACK,
        DeployStatus.CANCELLED,
    )

    @staticmethod
    async def release_expired_locks(db: AsyncSession) -> list[dict]:
        """释放已过期且未进入执行的写锁（供调度器周期调用），返回被释放的锁列表。"""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        locks = list((await db.execute(select(DeviceWriteLock))).scalars().all())
        released: list[dict] = []
        for lock in locks:
            if lock.expire_at is None or lock.expire_at > now:
                continue
            task = await db.get(DeployTask, lock.task_id)
            if task is not None and task.status not in DeployService._EXPIRABLE_TASK_STATUSES:
                logger.warning(
                    "lock_expired_but_task_active",
                    device_id=lock.device_id, task_id=lock.task_id,
                    status=getattr(task.status, "value", task.status),
                )
                continue
            # Re-check database state in the DELETE: the task may have been
            # claimed since this scheduler session loaded it.
            result = await db.execute(
                delete(DeviceWriteLock).where(
                    DeviceWriteLock.device_id == lock.device_id,
                    DeviceWriteLock.task_id == lock.task_id,
                    DeviceWriteLock.expire_at <= now,
                    ~exists(select(DeployTask.id).where(
                        DeployTask.id == lock.task_id,
                        DeployTask.status.not_in(DeployService._EXPIRABLE_TASK_STATUSES),
                    )),
                ).execution_options(synchronize_session="fetch")
            )
            if result.rowcount == 1:
                released.append({"device_id": lock.device_id, "task_id": lock.task_id})
        if released:
            await db.commit()
            # 审计的 user_id 是 NOT NULL 外键，而清理动作由调度器发起、没有真实操作人：
            # 取一个真实管理员 id 满足外键，username 如实写 "system"（不冒充该管理员）。
            from modules.auth.models import User, UserRole

            admin = (
                await db.execute(
                    select(User).where(User.role == UserRole.ADMIN).order_by(User.id).limit(1)
                )
            ).scalars().first()
            if admin is None:
                logger.warning("expired_locks_released_without_audit", count=len(released))
            else:
                for item in released:
                    await AuditService.log(
                        db, admin.id, "system", "deploy", "device_write_lock_released", "deploy_task",
                        str(item["task_id"]),
                        {
                            "task_id": item["task_id"],
                            "device_id": item["device_id"],
                            "result": "expired",
                            "reason": "lock_ttl_expired",
                        },
                    )
            logger.info("expired_locks_released", count=len(released))
        return released

    @staticmethod
    async def execute_task(db: AsyncSession, task_id: int, user: dict) -> dict:
        """执行4C已确认且持锁的任务；默认模拟，真实路径仅mock测试。"""
        task = await db.get(DeployTask, task_id)
        if not task:
            raise ValueError("任务状态不允许执行")
        if task.operator_id != user["user_id"] and user.get("role") != "admin":
            raise PermissionError("无权执行此任务")
        if task.status != DeployStatus.CONFIRMED:
            raise ValueError("任务状态不允许执行")
        lock = await db.get(DeviceWriteLock, task.device_id)
        if not lock or lock.task_id != task.id:
            raise ValueError("当前任务没有设备写锁")

        await DeployService._claim_task(db, task, DeployStatus.CONFIRMED, DeployStatus.DEPLOYING)

        settings = get_settings()
        # AF-02：在做出任何设备动作之前固化本次模式，失败/部分执行也能解释
        task.execution_mode = "simulated" if settings.deploy_simulate_only else "real"
        await db.commit()
        if settings.deploy_simulate_only:
            result = {
                "task_id": task.id, "device_id": task.device_id, "mode": "simulated",
                "steps": ["validate confirmed task", "would send config", "would read running-config"],
            }
            lock.lock_type = "deploy_simulated_ready"
            await AuditService.log(
                db, user["user_id"], user.get("username", ""), "deploy",
                "deploy_task_executed", "deploy_task", str(task.id),
                {"task_id": task.id, "device_id": task.device_id, "mode": "simulated", "result": "simulated"},
            )
            await db.commit()
            return result

        # 真实路径只在服务端显式关闭模拟开关后可达；测试始终使用mock执行器。
        device = await db.get(Device, task.device_id)
        if not await DeployService._is_authorized_stage4_target(db, device):
            # 拒绝也要释放写锁，否则设备被永久锁死
            task.status = DeployStatus.FAILED
            task.error_message = "deploy_target_not_allowlisted"
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "released_not_allowlisted"}, result="failed")
            raise ValueError("设备不在受控执行白名单")
        from engines.device_adapter import get_device_adapter
        adapter = None
        try:
            adapter = await get_device_adapter(device)
            task.backup_config = await adapter.run_command("display current-configuration")
            if not task.backup_config.strip():
                raise ValueError("执行前未取得配置备份，已拒绝写入")
            ConfigVerifier.raise_on_cli_error(task.backup_config)
            if (task.config_watermark or "").startswith("rollback_from_version:"):
                task.verify_diff = ConfigVerifier.verify_snapshot(task.config_content, task.backup_config)
                commands = ConfigVerifier.build_restore_commands(task.backup_config, task.config_content)
            else:
                ConfigVerifier.build_incremental_restore_commands(task.backup_config, task.config_content)
                commands = task.config_content.splitlines()
            await DeployService._assert_saved_matches_running(adapter, task.backup_config)
            # The original recovery evidence must survive a process loss after the
            # first device mutation; the executing lease stays held across this commit.
            await db.commit()
            if commands:
                ConfigVerifier.raise_on_cli_error(await adapter.send_config(commands))
                ConfigVerifier.raise_on_cli_error(await adapter.save_config())
            task.result_output = await adapter.run_command("display current-configuration")
            await DeployService._assert_saved_matches_running(adapter, task.result_output)
            result = {
                "task_id": task.id, "device_id": task.device_id, "mode": "real",
                "steps": ["config sent", "running-config read"],
            }
            audit_result = "executed"
        except Exception as exc:
            # 失败必须落状态与错误，否则 UI 永远显示"下发中"，且后续 verify 会把
            # "没有回读"误判成模拟执行成功（见 verify_task）。
            task.status = DeployStatus.FAILED
            task.error_message = type(exc).__name__
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.delete(lock)
            await db.commit()
            await AuditService.log(
                db, user["user_id"], user.get("username", ""), "deploy",
                "deploy_task_executed", "deploy_task", str(task.id),
                {"task_id": task.id, "device_id": task.device_id, "mode": "real",
                 "result": "error", "error_category": type(exc).__name__},
                result="error",
            )
            await AuditService.log(db, user["user_id"], user.get("username", ""), "deploy", "device_write_lock_released", "deploy_task", str(task.id), {"task_id": task.id, "device_id": task.device_id, "result": "released"}, result="failed")
            return {
                "task_id": task.id, "device_id": task.device_id, "mode": "real",
                "error_category": type(exc).__name__,
            }
        finally:
            if adapter is not None:
                await adapter.close()
        lock.lock_type = "deploy_ready"
        await AuditService.log(
            db, user["user_id"], user.get("username", ""), "deploy",
            "deploy_task_executed", "deploy_task", str(task.id),
            {"task_id": task.id, "device_id": task.device_id, "mode": "real", "result": audit_result},
            result=audit_result,
        )
        await db.commit()
        return result

    @staticmethod
    async def create_pending_tasks(db: AsyncSession, device_ids: list, config_content: str, template_id: int = None, change_level: ChangeLevel = ChangeLevel.DAILY, engine: str = "netmiko", operator_id: int = None) -> dict:
        """创建待人工确认的任务；阶段4C不连接或操作设备。"""
        devices = []
        for dev_id in device_ids:
            device = await db.get(Device, dev_id)
            if not device:
                raise ValueError(f"设备不存在: {dev_id}")
            if device.status != DeviceStatus.ONLINE:
                raise ValueError(f"设备 {device.hostname} 状态为 {device.status.value}，不允许下发")
            devices.append(device)

        transaction_id = str(uuid.uuid4())[:12]
        results = {"transaction_id": transaction_id, "total": len(devices), "success": 0, "failed": 0, "rolled_back": 0, "details": []}
        validator = VRPValidator()
        for device in devices:
            report = validator.assess(config_content, device.model or "unknown")
            if not report["valid"]:
                raise ValueError(f"设备 {device.hostname} 配置被阻断: {report['errors']}")
            task = DeployTask(
                transaction_id=transaction_id, device_id=device.id, config_content=config_content,
                template_id=template_id, status=DeployStatus.AWAITING_CONFIRMATION,
                engine=engine, change_level=(ChangeLevel.HIGH_RISK if report["requires_confirmation"] else change_level), operator_id=operator_id,
                config_watermark=await DeployService._config_watermark(db, device.id),
            )
            db.add(task)
            await db.flush()
            results["details"].append({
                "device_id": device.id,
                "hostname": device.hostname,
                "status": task.status.value,
                "task_id": task.id,
                "risk_level": DeployService._highest_risk(report["details"]),
                "requires_confirmation": report.get("requires_confirmation", False),
            })
        # 统计此前恒为 0（只 append 了 details），前端拿到的 success/failed 永远是 0
        results["success"] = len(results["details"])
        results["total"] = len(devices)
        await db.commit()
        return results

    @staticmethod
    async def create_rollback_task(db: AsyncSession, version_id: int, user: dict) -> dict:
        """B2：由历史配置版本生成"受控回滚任务"。

        关键设计：**不直接执行回滚**，而是用该版本的快照内容创建一个高风险下发任务，
        随后完全走既有的"人工确认（高风险二次确认）→ 写锁 → 执行 → 回读验证"链路。
        这样回滚不会绕过确认、写锁与白名单（旧入口 `/config-versions/{id}/rollback`
        正是因为会绕过这些校验而被禁用）。
        """
        version = await db.get(ConfigVersion, version_id)
        if not version:
            raise ValueError("配置版本不存在")
        if user.get("role") != "admin" and version.created_by != user["user_id"]:
            raise PermissionError("无权回滚此配置版本")

        device = await db.get(Device, version.device_id)
        if not device:
            raise ValueError("设备不存在")
        if not (version.config_snapshot or "").strip():
            raise ValueError("该版本没有配置快照，无法回滚")

        # 回滚同样是"命令行下发"，先过与正常下发一致的破坏性命令检查
        forbidden = VRPValidator.check_rollback_safe(version.config_snapshot or "")
        if forbidden:
            raise ValueError(f"回滚内容包含被禁止的命令: {forbidden}")

        transaction_id = str(uuid.uuid4())[:12]
        task = DeployTask(
            transaction_id=transaction_id,
            device_id=device.id,
            config_content=version.config_snapshot,
            status=DeployStatus.AWAITING_CONFIRMATION,
            engine="netmiko",
            change_level=ChangeLevel.HIGH_RISK,
            operator_id=user["user_id"],
            config_watermark=f"rollback_from_version:{version.id}/v{version.version_number}",
        )
        db.add(task)
        await db.flush()
        await db.commit()
        await AuditService.log(
            db, user["user_id"], user.get("username", ""), "deploy", "deploy_rollback_task_created",
            "deploy_task", str(task.id),
            {
                "task_id": task.id,
                "device_id": device.id,
                "source_version_id": version.id,
                "source_version_number": version.version_number,
                "change_level": "high_risk",
                "result": "awaiting_confirmation",
            },
        )
        return {
            "task_id": task.id,
            "device_id": device.id,
            "hostname": device.hostname,
            "status": task.status.value,
            "source_version_id": version.id,
            "source_version_number": version.version_number,
        }

    @staticmethod
    async def _config_watermark(db: AsyncSession, device_id: int) -> str | None:
        """记录本次下发所依据的配置快照（P2-06：此前该字段无任何写入点）。

        取设备最新的一版配置快照，形如 ``config_version:12/v3``；设备还没有快照时
        返回 None。该字段只作溯源展示，不参与任何判定。
        """
        row = (
            await db.execute(
                select(ConfigVersion.id, ConfigVersion.version_number)
                .where(ConfigVersion.device_id == device_id)
                .order_by(ConfigVersion.version_number.desc())
                .limit(1)
            )
        ).first()
        if not row:
            return None
        return f"config_version:{row[0]}/v{row[1]}"

    @staticmethod
    def _highest_risk(details: list) -> str:
        """取最高风险等级（此前按行序取第一个非 safe，可能低估）。"""
        highest = RiskLevel.SAFE
        for detail in details or []:
            level = detail.get("risk_level") or RiskLevel.SAFE
            if RiskLevel.ORDER.get(level, 0) > RiskLevel.ORDER.get(highest, 0):
                highest = level
        return highest

    @staticmethod
    async def _next_version_number(db: AsyncSession, device_id: int) -> int:
        """获取设备下一个配置版本号"""
        result = await db.execute(
            select(ConfigVersion.version_number)
            .where(ConfigVersion.device_id == device_id)
            .order_by(ConfigVersion.version_number.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        return (last or 0) + 1
