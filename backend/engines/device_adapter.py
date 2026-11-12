"""设备访问适配层：SSH（真机/eNSP）与 Sim（离线模拟）统一入口。

配置：DEVICE_MODE 环境变量（core.config.device_mode）
  - "ssh"（默认）：真机 / eNSP，走 engines.NetmikoExecutor（保留原有行为）
  - "sim"：离线模拟，SimDeviceAdapter 返回脚本化 VRP 回显，不产生任何网络连接，
    用于无 eNSP / 无设备凭据时跑通 健康检查、LLDP 拓扑、监控采集、配置快照、
    下发预检→确认→执行（模拟）→验证、实训 hint/报告 全链路。

接入 eNSP 时把 DEVICE_MODE 改回 "ssh" 并配置设备凭据即可，业务代码无需改动。
"""
import hashlib
import random
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from core.config import get_settings
from core.logger import get_logger

logger = get_logger("device")


def get_device_mode() -> str:
    """当前设备执行模式：ssh | sim。"""
    return (get_settings().device_mode or "ssh").strip().lower()


# ── 模拟设备 VRP 回显语料 ─────────────────────────────────────────────
# 输出格式与 modules/monitor/service.py 的解析器、modules/device/lldp_parser.py 对齐。
_SIM_VERSION = """<{hostname}>display version
Huawei Versatile Routing Platform Software
VRP (R) software, Version 8.180 (CE6800 V200R005C20SPC607B607)
Copyright (C) 2012-2020 Huawei Technologies Co., Ltd.
Uptime is 3 weeks, 4 days, 6 hours, 12 minutes
"""

_SIM_CPU = """<{hostname}>display cpu-usage
CPU Usage Stat. Cycle: 30 (Second)
CPU Usage            : {cpu}%
CPU Usage Stat.      : {cpu}%    Max: {maxcpu}%    Min: {mincpu}%
"""

_SIM_MEMORY = """<{hostname}>display memory-usage
Memory Using Percentage: {mem}%
Memory Total: 8192 MB
Memory Used : {used} MB
"""

_SIM_INTERFACE = """<{hostname}>display interface brief
PHY: Physical
Interface                PHY   Protocol  InUti OutUti   inErrors  outErrors
GigabitEthernet0/0/0     up    up        0.01%  0.01%          0          0    10.0.123.1/24
GigabitEthernet0/0/1     up    up        0.01%  0.01%          0          0    10.0.123.2/24
GigabitEthernet0/0/2     down  down      0.00%  0.00%          0          0
GigabitEthernet0/0/3     up    up        0.01%  0.01%          0          0    10.0.0.1/24
"""

_SIM_OSPF = """<{hostname}>display ospf peer brief
 Area 0.0.0.0 interface GigabitEthernet0/0/0
 RouterId     Address          State        UpTime
 10.0.0.2     10.0.1.2         Full         00:12:34
"""

_SIM_BGP = """<{hostname}>display bgp peer
 BGP local router ID : 10.0.0.1
 Total number of peers : 2
 Peer            V          AS  MsgRcvd  MsgSent  OutQ  Up/Down  State  PrefRcv
 10.0.0.2        4          65001       1234     1234     0  00:12:34 Established      512
"""

_SIM_TEMPERATURE = """<{hostname}>display temperature
Board 1:
  Current temperature: 41.5 degrees Celsius
  Highest temperature: 45.2 degrees Celsius
  Lowest temperature:  38.0 degrees Celsius
  Board temperature is OK
"""

_SIM_CONFIG_TEMPLATE = """<{hostname}>display current-configuration
!Software Version V200R005C20SPC607B607
sysname {hostname}
#
interface GigabitEthernet0/0/0
 undo shutdown
 ip address 192.168.100.{ip_last} 255.255.255.0
#
interface GigabitEthernet0/0/1
 undo shutdown
#
interface GigabitEthernet0/0/3
 undo shutdown
#
ospf 1
 area 0.0.0.0
  network 10.0.1.0 0.0.0.255
#
return
"""


class BaseDeviceAdapter(ABC):
    """设备访问统一接口。"""

    name: str = "base"

    @abstractmethod
    async def run_command(self, command: str, timeout: float | None = None) -> str:
        """执行命令（display/配置均可），返回回显文本。"""

    @abstractmethod
    async def send_config(self, commands: list[str]) -> str:
        """下发配置命令列表，返回回显。"""

    @abstractmethod
    async def save_config(self) -> str:
        """保存配置。"""

    @abstractmethod
    async def check_online(self) -> bool:
        """探测设备可达性。"""

    async def close(self) -> None:
        """释放连接资源（可空实现）。"""


class SSHDeviceAdapter(BaseDeviceAdapter):
    """SSH 执行适配：真机 / eNSP。懒连接 + 复用 engines.NetmikoExecutor。"""

    name = "ssh"

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 22,
        timeout: int = 10,
        device_model: str = "",
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.device_model = device_model
        self._executor: Any | None = None

    async def _ensure(self):
        if self._executor is None:
            # 延迟导入：保持对 engines.netmiko_exec.NetmikoExecutor 的动态引用，
            # 以便测试 monkeypatch 该模块属性时本类跟随生效。
            from engines.netmiko_exec import NetmikoExecutor
            self._executor = NetmikoExecutor(
                host=self.host,
                username=self.username,
                password=self.password,
                port=self.port,
                timeout=self.timeout,
                device_model=self.device_model,
            )
            await self._executor.connect()
        return self._executor

    async def run_command(self, command: str, timeout: float | None = None) -> str:
        from engines.device_lock import acquire_device_lock
        deadline = None if timeout is None else time.monotonic() + timeout
        async with acquire_device_lock(self.host, self.port):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("SSH command deadline expired")
            executor = await self._ensure()
            if deadline is None:
                return await executor.send_command(command)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("SSH command deadline expired during connection")
            return await executor.send_command(command, timeout=remaining)

    async def send_config(self, commands: list[str]) -> str:
        from engines.device_lock import acquire_device_lock
        async with acquire_device_lock(self.host, self.port):
            executor = await self._ensure()
            return await executor.send_config_set(commands)

    async def save_config(self) -> str:
        from engines.device_lock import acquire_device_lock
        async with acquire_device_lock(self.host, self.port):
            executor = await self._ensure()
            return await executor.save_config()

    async def check_online(self) -> bool:
        from engines.device_lock import acquire_device_lock
        from engines.ssh_exec import SSHExecutor
        async with acquire_device_lock(self.host, self.port):
            ssh = SSHExecutor(
                host=self.host,
                username=self.username,
                password=self.password,
                port=self.port,
                timeout=min(self.timeout, 8),
            )
            try:
                await ssh.connect()
                return True
            except Exception as exc:
                logger.debug("ssh_online_check_failed", host=self.host, error=str(exc))
                return False
            finally:
                await ssh.disconnect()

    async def close(self) -> None:
        if self._executor is not None:
            try:
                await self._executor.disconnect()
            except Exception:
                pass
            self._executor = None


class SimDeviceAdapter(BaseDeviceAdapter):
    """离线模拟适配：返回脚本化 VRP 回显，不做任何网络连接。

    - 数值由 hostname 哈希派生（同一设备每次稳定，不同设备有差异）
    - LLDP 邻居从上下文 neighbors（同拓扑其它设备）中确定性选取，
      使 LLDP 拓扑发现能在模拟环境下产出真实链路
    - 配置下发在内存中记录，display current-configuration 会包含已下发内容
    """

    name = "sim"

    def __init__(self, hostname: str, neighbors: list[str] | None = None):
        self.hostname = hostname
        self.neighbors = [n for n in (neighbors or []) if n != hostname]
        self._applied: list[str] = []
        digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()
        seed = int(digest[:8], 16)
        # 保存派生种子：display current-configuration 里的地址也用它，
        # 不再用内置 hash()（受 PYTHONHASHSEED 影响，跨进程不稳定，与"同一设备每次稳定"矛盾）
        self._seed = seed
        self._rng = random.Random(seed)
        self._cpu = self._rng.randint(8, 92)
        self._mem = self._rng.randint(25, 88)

    # ── 内部工具 ──────────────────────────────────────────────────────
    def _pick_neighbor(self, index: int) -> str:
        if not self.neighbors:
            return "SW-UNKNOWN"
        return self.neighbors[index % len(self.neighbors)]

    def _current_config(self) -> str:
        ip_last = (self._seed % 240) + 10
        body = _SIM_CONFIG_TEMPLATE.format(hostname=self.hostname, ip_last=ip_last)
        if self._applied:
            applied = "\n".join(f" {line}" for line in self._applied)
            body += f"#  [sim-applied]\n{applied}\n#\n"
        return body

    # ── 统一接口 ──────────────────────────────────────────────────────
    async def run_command(self, command: str, timeout: int | None = None) -> str:
        cmd = re.sub(r"\s+", " ", (command or "").strip().lower())
        if "display version" in cmd:
            return _SIM_VERSION.format(hostname=self.hostname)
        if "cpu-usage" in cmd:
            return _SIM_CPU.format(hostname=self.hostname, cpu=self._cpu, maxcpu=min(self._cpu + self._rng.randint(1, 6), 99), mincpu=max(self._cpu - self._rng.randint(1, 6), 1))
        if "memory-usage" in cmd:
            used = int(8192 * self._mem / 100)
            return _SIM_MEMORY.format(hostname=self.hostname, mem=self._mem, used=used)
        # 先匹配更具体的完整命令，避免 brief/detail 互相遮蔽（L2 授权小修）
        if "display ip interface brief" in cmd:
            return (
                f"<{self.hostname}>display ip interface brief\n"
                "Interface                         PHY   Protocol  IP Address\n"
                "GigabitEthernet0/0/0  up  up  10.0.123.1/24\n"
                "GigabitEthernet0/0/1  up  up  10.0.123.2/24\n"
                "LoopBack0             up  up  10.0.0.1/24\n"
            )
        if "display interface brief" in cmd:
            return _SIM_INTERFACE.format(hostname=self.hostname)
        if "display ospf peer brief" in cmd:
            return _SIM_OSPF.format(hostname=self.hostname)
        if "display ospf peer" in cmd:
            return (
                f"<{self.hostname}>display ospf peer\n"
                "OSPF Process 1 with Router ID 10.0.0.1\n"
                " Neighbor brief information\n"
                "Area 0.0.0.0 interface GigabitEthernet3/0/3's neighbors\n"
                "Router ID: 10.0.0.2   Address: 10.0.123.2\n"
                "State: Full  Mode:Nbr is Master  Priority: 1\n"
                "DR: 10.0.123.1  BDR: 10.0.123.2  MTU: 0\n"
            )
        if "ospf peer" in cmd:
            return _SIM_OSPF.format(hostname=self.hostname)
        if "bgp peer" in cmd:
            return _SIM_BGP.format(hostname=self.hostname)
        if "temperature" in cmd:
            return _SIM_TEMPERATURE.format(hostname=self.hostname)
        if "lldp neighbor" in cmd:
            n1 = self._pick_neighbor(0)
            n2 = self._pick_neighbor(1) if len(self.neighbors) > 1 else self._pick_neighbor(0)
            return (
                f"<{self.hostname}>display lldp neighbor brief\n"
                "Local Intf    Neighbor Dev    Neighbor Intf    Neighbor TTL    Exptime(s)\n"
                f"GE0/0/1       {n1}            GE0/0/1          120              118\n"
                f"GE0/0/3       {n2}            GE0/0/2          120              118\n"
                "Info: The max number of neighbors is 256\n"
            )
        if "display ip interface brief" in cmd:
            return (
                f"<{self.hostname}>display ip interface brief\n"
                "Interface                         PHY   Protocol  InUti OutUti   inErrors  outErrors\n"
                "GigabitEthernet0/0/0  up  up  10.0.123.1/24\n"
                "GigabitEthernet0/0/1  up  up  10.0.123.2/24\n"
                "LoopBack0             up  up  10.0.0.1/24\n"
            )
        if "display ospf peer" in cmd:
            return (
                f"<{self.hostname}>display ospf peer\n"
                "OSPF Process 1 with Router ID 10.0.0.1\n"
                " Neighbor brief information\n"
                "Area 0.0.0.0 interface GigabitEthernet3/0/3's neighbors\n"
                "Router ID       Address         Pri  Dead-Time  State    Up/Down Time\n"
                "10.0.0.2       10.0.123.2       1    00:00:36   Full     00:12:08\n"
                "10.0.0.3       10.0.123.3       1    00:00:31   Full     00:11:42\n"
            )
        if cmd == "display ip routing-table":
            # The existing interface fixture supplies these local addresses.
            # Provide actual fields instead of acknowledging an unread table.
            return (
                f"<{self.hostname}>display ip routing-table\n"
                "Destination/Mask Proto Pre Cost Flags NextHop Interface\n"
                "10.0.123.0/24 Direct 0 0 D 10.0.123.1 GigabitEthernet0/0/0\n"
                "10.0.0.0/24 Direct 0 0 D 10.0.0.1 LoopBack0\n"
            )
        if "display ospf routing" in cmd:
            return (
                f"<{self.hostname}>display ospf routing\n"
                "Destinations        : 3\n"
                "Destination        Cost  Type       NextHop         AdvRouter       Area\n"
                "10.0.0.2/32        1     Stub       10.0.123.2      10.0.0.2        0.0.0.0\n"
                "10.0.0.3/32        1     Stub       10.0.123.3      10.0.0.3        0.0.0.0\n"
                "10.0.9.9/32        2     Stub       10.0.123.2      10.0.0.2        0.0.0.0\n"
            )
        if "current-configuration" in cmd:
            return self._current_config()
        if "sysname" in cmd or cmd.startswith("return") or cmd == "quit":
            return f"<{self.hostname}>"
        if cmd.startswith('display '):
            return f"<{self.hostname}>{command}\nError: Command is not supported by the offline simulator."
        # 其它命令：模拟 VRP 风格响应
        return f"<{self.hostname}>{command}\nInfo: (sim) 已执行 {command}"

    async def send_config(self, commands: list[str]) -> str:
        applied = [c for c in commands if c.strip()]
        self._applied.extend(applied)
        lines = [f"[{self.hostname}] {c}" for c in applied]
        return "\n".join(lines) + (f"\nInfo: (sim) 已应用 {len(applied)} 条配置命令" if applied else "")

    async def save_config(self) -> str:
        return "Info: The configuration is saved in the device (sim)"

    async def check_online(self) -> bool:
        return True

    async def close(self) -> None:
        return None


async def get_device_adapter(
    device: Any,
    *,
    neighbors: list[str] | None = None,
) -> BaseDeviceAdapter:
    """按 device_mode 构造设备适配器。

    device: 具有 hostname/mgmt_ip/ssh_port 属性的设备对象（ORM 或测试替身）。
    neighbors: sim 模式下 LLDP 响应的邻居候选（同拓扑其它设备 hostname）。
    """
    mode = get_device_mode()
    if mode == "sim":
        return SimDeviceAdapter(hostname=getattr(device, "hostname", "sim-device"), neighbors=neighbors)

    from modules.device.service import DeviceService  # 延迟导入避免循环依赖
    credentials = await DeviceService.get_device_credentials(device)
    settings = get_settings()
    return SSHDeviceAdapter(
        host=getattr(device, "mgmt_ip", "") or "",
        username=credentials.get("username", "") or "",
        password=credentials.get("password", "") or "",
        port=getattr(device, "ssh_port", None) or 22,
        timeout=settings.ssh_connect_timeout,
        device_model=getattr(device, "model", "") or "",
    )
