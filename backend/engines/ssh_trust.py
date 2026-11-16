"""设备 SSH 的主机身份校验和认证。"""
from base64 import b64encode
from hashlib import sha256
from pathlib import Path

import paramiko
from paramiko.hostkeys import HostKeyEntry

from core.config import get_settings
from core.logger import get_logger

logger = get_logger("ssh")


class UnknownDeviceHost(paramiko.SSHException):
    pass


class InvalidKnownHosts(paramiko.SSHException):
    pass


class RejectUnknownDevice(paramiko.RejectPolicy):
    def missing_host_key(self, client, hostname, key):
        fingerprint = b64encode(sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")
        raise UnknownDeviceHost(f"尚未登记 SSH 主机 {hostname}（SHA256:{fingerprint}）")


def _load_pinned_keys(client: paramiko.SSHClient, filename: str) -> None:
    path = Path(filename).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError) as exc:
        raise InvalidKnownHosts("无法读取配置的 SSH 已知主机文件，请检查路径、权限和编码。") from exc
    keys = client.get_host_keys()
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entry = HostKeyEntry.from_line(" ".join(line.split()[:3]), number)
            if entry is None or entry.key is None:
                raise ValueError("invalid entry")
            for hostname in entry.hostnames:
                if not hostname:
                    raise ValueError("empty host")
                known = keys.lookup(hostname)
                key_type = entry.key.get_name()
                if known and key_type in known and known[key_type] != entry.key:
                    raise ValueError("conflicting host keys")
                keys.add(hostname, key_type, entry.key)
        except Exception as exc:
            raise InvalidKnownHosts(f"SSH 已知主机文件第 {number} 行无效，请核对登记记录。") from exc
    if not keys:
        raise InvalidKnownHosts("SSH 已知主机文件为空，请先登记已核对的设备密钥。")


def new_ssh_client() -> paramiko.SSHClient:
    settings = get_settings()
    client = paramiko.SSHClient()
    if not settings.ssh_strict_host_key:
        logger.warning("ssh_host_validation_disabled")
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        return client
    if settings.ssh_known_hosts:
        # An explicitly managed file is authoritative for workbench inventory.
        _load_pinned_keys(client, settings.ssh_known_hosts)
    else:
        client.load_system_host_keys()
    client.set_missing_host_key_policy(RejectUnknownDevice())
    return client


def connect_with_device_password(
    client: paramiko.SSHClient, host: str, port: int, username: str, password: str, timeout: float,
) -> None:
    try:
        client.connect(hostname=host, port=port, username=username, password=password,
                       timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
                       channel_timeout=timeout, allow_agent=False, look_for_keys=False)
    except paramiko.AuthenticationException:
        # Paramiko verifies the host before authentication. Stay on that
        # transport when a device only accepts keyboard-interactive.
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise
        transport.auth_interactive(username, lambda _title, _instructions, prompts: [password] * len(prompts))
        if not transport.is_authenticated():
            raise paramiko.AuthenticationException("设备拒绝了交互式 SSH 登录")
