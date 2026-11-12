"""Netmiko SSH执行器"""
import asyncio
import re
import threading
from netmiko.huawei.huawei import HuaweiSSH, HuaweiVrpv8SSH
from core.logger import get_logger

logger = get_logger("ssh")


_CONFIG_ERROR = r"(?im)^\s*(?:error\s*:|failure\s*:|failed\b|%\s|unrecognized command|wrong parameter|incomplete command|too many parameters|ambiguous command)"
_CONFIRMATION_PROMPT = r"(?i:\[(?:y/n|n/y|yes/no|no/yes)\]\s*:?)"
_LLDP_DISABLE_WARNING = "Warning: This command will delete the configurations of LLDP on all the ports. Continue? [Y/N]:"


def _check_config_output(output: str) -> None:
    if re.search(_CONFIG_ERROR, output or ""):
        raise ValueError("device rejected configuration operation")


async def _run_ssh_operation(operation, *, on_cancel=None):
    """A cancelled coroutine must retain its lock until the SSH thread settles."""
    future = asyncio.get_running_loop().run_in_executor(None, operation)
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        if on_cancel is not None:
            on_cancel()
        # Cancelling an executor Future cannot stop Paramiko/Netmiko. Draining the
        # bounded operation avoids disconnecting or reusing its channel mid-read.
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not future.cancelled():
            future.exception()  # Retrieve a worker failure while preserving cancellation.
        raise


class SafeHuaweiSSH(HuaweiSSH):
    """Never accept a configuration repair/save as a side effect of SSH login."""

    def special_login_handler(self, delay_factor: float = 1.0) -> None:
        try:
            data = self.read_until_pattern(pattern=self.prompt_or_password_change)
            risk_prompt = r"security\s+risks\s+in\s+the\s+configuration\s+file"
            if re.search(risk_prompt, data, re.I):
                raise RuntimeError("configuration security prompt requires manual review; connection refused")
            if re.search(self.password_change_prompt, data):
                self.write_channel("N" + self.RETURN)
                data = self.read_until_pattern(pattern=self.prompt_pattern)
                if re.search(risk_prompt, data, re.I):
                    raise RuntimeError("configuration security prompt requires manual review; connection refused")
        except Exception:
            # Login runs inside the driver constructor, before the executor receives
            # the object. Close transport directly: cleanup() would send CLI text into
            # an untrusted confirmation prompt and the outer adapter cannot close it.
            for name in ("remote_conn", "remote_conn_pre"):
                channel = getattr(self, name, None)
                if channel is not None:
                    try:
                        channel.close()
                    except Exception:
                        pass
            raise


class SafeHuaweiVrpv8SSH(SafeHuaweiSSH, HuaweiVrpv8SSH):
    """Explicit candidate commit; disconnect never answers a commit prompt."""

    def send_config_set(self, config_commands=None, exit_config_mode=False, *,
                        allow_lldp_disable_confirmation=False, cancel_event=None, **kwargs):
        commands = [config_commands] if isinstance(config_commands, str) else list(config_commands or [])
        enter = kwargs.pop("enter_config_mode", True)
        kwargs.pop("terminator", None)
        output = ""
        prompt = rf"\[[~*]{re.escape(self.base_prompt)}(?:-[^\r\n\]]+)?\]\s*$"

        def check_cancelled():
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("configuration operation cancelled before next write")

        if enter and commands:
            check_cancelled()
            config_command = kwargs.pop("config_mode_command", None)
            entered = self.config_mode(config_command) if config_command else self.config_mode()
            _check_config_output(entered)
            if re.search(_CONFIRMATION_PROMPT, entered):
                raise ValueError("unapproved configuration-mode confirmation prompt")
            # Entering system-view can emit unrelated chassis warnings. Keep that
            # output for audit, but never interpret it as the following command's
            # confirmation (nor discard it by taking the last warning in a blob).
            output += entered
        for command in commands:
            check_cancelled()
            part = super().send_config_set(
                [command], exit_config_mode=False, enter_config_mode=False,
                terminator=_CONFIRMATION_PROMPT, **kwargs,
            )
            _check_config_output(part)
            check_cancelled()
            if re.search(_CONFIRMATION_PROMPT, part):
                warning = " ".join(part[part.find("Warning:"):].split()) if "Warning:" in part else ""
                if (command.strip().lower() != "undo lldp enable"
                        or not allow_lldp_disable_confirmation or warning != _LLDP_DISABLE_WARNING):
                    raise ValueError("unapproved configuration confirmation prompt")
                check_cancelled()
                reply = self._send_command_str(
                    "Y", expect_string=rf"(?:{prompt}|{_CONFIRMATION_PROMPT})",
                    strip_command=False, strip_prompt=False, cmd_verify=False,
                    read_timeout=kwargs.get("read_timeout", 15),
                )
                _check_config_output(reply)
                if re.search(_CONFIRMATION_PROMPT, reply) or not re.search(prompt, reply, re.M):
                    raise ValueError("LLDP confirmation did not return the device prompt")
                part += reply
            output += part
        check_cancelled()
        if exit_config_mode:
            output += self.exit_config_mode()
        return output

    def commit(self, read_timeout: float = 120.0, **kwargs) -> str:
        entered = self.config_mode()
        _check_config_output(entered)
        output = self._send_command_str(
            "commit", strip_prompt=False, strip_command=False,
            read_timeout=read_timeout, expect_string=r"\[[~*][^\r\n\]]+\]",
        )
        _check_config_output(output)
        if not re.search(r"(?m)^\s*\[~[^\r\n\]]+\]\s*$", output):
            raise ValueError("candidate commit not confirmed by clean VRP8 prompt")
        exited = self.exit_config_mode()
        _check_config_output(exited)
        return "\n".join((entered, output, exited))

    def cleanup(self, command: str = "quit") -> None:
        # Base disconnect() closes Paramiko and log resources after this hook.
        # No return/quit/confirmation is safe when a candidate operation failed.
        pass


def new_ssh_client():
    """按配置构造 paramiko SSHClient。

    默认 AutoAddPolicy（eNSP/虚拟镜像会频繁重装，主机密钥不稳定）；
    设置 SSH_STRICT_HOST_KEY=true 后改为校验 known_hosts（真实设备环境建议开启）。
    """
    import paramiko
    from core.config import get_settings

    settings = get_settings()
    client = paramiko.SSHClient()
    if getattr(settings, "ssh_strict_host_key", False):
        client.load_system_host_keys()
        known_hosts = getattr(settings, "ssh_known_hosts", "") or ""
        if known_hosts:
            try:
                client.load_host_keys(known_hosts)
            except OSError as exc:
                logger.warning("ssh_known_hosts_load_failed", path=known_hosts, error=str(exc))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


class NetmikoExecutor:
    def __init__(self, host: str, username: str, password: str, port: int = 22, timeout: int = 10,
                 device_model: str = ""):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.device_model = device_model or ""
        self._write_capability_checked = False
        self._commit_succeeded = False
        # 单条命令的读取超时：此前没传 read_timeout，命令可无限阻塞线程池并长期
        # 占用设备锁（device_lock 的 8s 只是"获取锁"超时，不含执行期）。
        from core.config import get_settings
        self.read_timeout = max(5, int(get_settings().ssh_command_timeout))
        self._device = None

    async def connect(self):
        device_params = {
            "device_type": "huawei_vrp",
            "host": self.host,
            "username": self.username,
            "password": self.password,
            "port": self.port,
            "timeout": self.timeout,
            "conn_timeout": self.timeout,
            "auth_timeout": self.timeout,
            "banner_timeout": self.timeout,
            "blocking_timeout": self.read_timeout,
        }
        driver = SafeHuaweiVrpv8SSH if self.device_model.upper().startswith("NE40E") else SafeHuaweiSSH
        def connect_sync():
            # Retain the connection even when cancellation arrives during login,
            # so the adapter's finally block can close it after the worker settles.
            self._device = driver(**device_params)
        await _run_ssh_operation(connect_sync)
        self._write_capability_checked = False
        self._commit_succeeded = False

    async def disconnect(self):
        if self._device:
            try:
                await _run_ssh_operation(self._device.disconnect)
            finally:
                self._device = None

    async def send_command(self, command: str, timeout: float | None = None) -> str:
        if not self._device:
            raise RuntimeError("未连接")
        read_timeout = self.read_timeout if timeout is None else min(self.read_timeout, timeout)
        if read_timeout <= 0:
            raise TimeoutError("SSH command deadline expired")
        return await _run_ssh_operation(
            lambda: self._device.send_command(command, read_timeout=read_timeout)
        )

    async def send_config_set(self, commands: list) -> str:
        if not self._device:
            raise RuntimeError("未连接")
        self._commit_succeeded = False
        # Inventory selects a driver; only a fresh real version response authorizes
        # the known NE40E/VRP8 write profile. Unknown models remain read-only.
        if not self._write_capability_checked:
            version = await self.send_command("display version")
            if (not self.device_model.upper().startswith("NE40E")
                    or not re.search(r"\bVRP\b[^\r\n]*\bVersion\s+8\.\d+\s+\(NE40E\b", version, re.I)):
                raise ValueError("actual device write capability is not supported NE40E VRP8")
            self._write_capability_checked = True
        prepared = [line.strip() for line in commands if line.strip() and not line.strip().startswith(("#", "!"))]
        if any(re.match(r"^(?:commit|save)\b", line, re.I) for line in prepared):
            raise ValueError("commit and save are controlled by the execution workflow")
        while prepared and prepared[0].lower() == "system-view":
            prepared.pop(0)
        while prepared and prepared[-1].lower() in {"return", "quit"}:
            prepared.pop()
        if not prepared or any(line.lower() in {"return", "system-view"} for line in prepared):
            raise ValueError("unsupported candidate configuration navigation")
        allow_lldp_disable = any(line.lower() == "undo lldp enable" for line in prepared)
        if allow_lldp_disable:
            # This confirmation deletes per-port settings, not just the global
            # flag. Authorize it only after a fresh complete read proves none exist.
            from modules.deploy.config_verifier import ConfigVerifier
            current = await self.send_command("display current-configuration")
            _check_config_output(current)
            state = ConfigVerifier._state(current)
            if not any(line.startswith("sysname ") for line in state.get((), set())):
                raise ValueError("LLDP confirmation preflight configuration unavailable")
            if any(re.match(r"^(?:undo\s+)?lldp(?:\s|$)", line, re.I)
                   for path, lines in state.items() if any(view.startswith("interface ") for view in path)
                   for line in lines):
                raise ValueError("interface LLDP configuration prevents global disable confirmation")
        cancelled = threading.Event()
        output = await _run_ssh_operation(lambda: self._device.send_config_set(
            prepared, exit_config_mode=False, error_pattern=_CONFIG_ERROR, read_timeout=self.read_timeout,
            allow_lldp_disable_confirmation=allow_lldp_disable, cancel_event=cancelled,
        ), on_cancel=cancelled.set)
        _check_config_output(output)
        committed = await _run_ssh_operation(lambda: self._device.commit(read_timeout=self.read_timeout))
        _check_config_output(committed)
        if not re.search(r"(?m)^\s*\[~[^\r\n\]]+\]\s*$", committed):
            raise ValueError("candidate commit did not produce a clean VRP8 prompt")
        self._commit_succeeded = True
        return output + committed

    async def save_config(self) -> str:
        if not self._device:
            raise RuntimeError("未连接")
        if not self._commit_succeeded:
            raise ValueError("save refused without a successful explicit commit")
        output = await _run_ssh_operation(lambda: self._device.save_config())
        _check_config_output(output)
        if not re.search(r"(?i)(?:sav(?:e|ed).*successfully|successfully.*sav(?:e|ed))", output or ""):
            raise ValueError("configuration save was not explicitly confirmed")
        return output


class SSHExecutor:
    """原生SSH执行器（paramiko封装）"""
    def __init__(self, host: str, username: str, password: str, port: int = 22, timeout: int = 10):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self._client = None
        self._channel = None

    async def connect(self):
        import paramiko
        self._client = new_ssh_client()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self._client.connect(
            hostname=self.host, port=self.port, username=self.username,
            password=self.password, timeout=self.timeout, allow_agent=False, look_for_keys=False
        ))

    async def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None

    async def execute(self, command: str, timeout: int = 30) -> str:
        if not self._client:
            raise RuntimeError("未连接")
        loop = asyncio.get_running_loop()
        stdin, stdout, stderr = await loop.run_in_executor(None, lambda: self._client.exec_command(command, timeout=timeout))
        return stdout.read().decode("utf-8", errors="replace")
