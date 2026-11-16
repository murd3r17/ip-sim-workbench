"""WebSSH代理 - WebSocket与SSH之间的双向数据转发"""
import asyncio
import paramiko
import json
import re
import socket
from contextlib import suppress
from typing import Awaitable, Callable
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from core.logger import get_logger
from core.config import get_settings
from engines.ssh_trust import InvalidKnownHosts, UnknownDeviceHost, connect_with_device_password
from modules.auth.terminal_grants import TerminalPermissionError

logger = get_logger("webssh")
_SIM_NAVIGATION_KEYS = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|O[@-~])")
_SIM_MAX_COMMAND_LENGTH = 4096


class SSHProxySession:
    """SSH代理会话 - 管理WebSocket与SSH之间的双向数据转发"""

    def __init__(self, websocket: WebSocket, device_ip: str, ssh_port: int, username: str, password: str, session_logger=None, device_hostname: str = "", authorize: Callable[[], Awaitable[bool]] | None = None):
        self.websocket = websocket
        self.device_ip = device_ip
        self.ssh_port = ssh_port
        self.username = username
        self.password = password
        self.session_logger = session_logger
        self.device_hostname = device_hostname or device_ip
        self._authorize = authorize
        self._ssh_client: paramiko.SSHClient | None = None
        self._channel: paramiko.Channel | None = None
        self._running = False

    async def _check_authorization(self) -> bool:
        if self._authorize is None:
            return True
        code, message = 4001, "登录状态已失效，请重新登录"
        try:
            valid = await self._authorize()
        except TerminalPermissionError:
            valid = False
            code, message = 4003, "终端授权已失效，请返回设备页做只读观察，或联系管理员。"
        except Exception:
            valid = False
        if not valid:
            self._running = False
            with suppress(Exception):
                await self.websocket.send_text(json.dumps({"type": "error", "message": message}))
                await self.websocket.close(code=code)
            await self.stop()
        return valid

    async def _watch_authorization(self):
        # Idle terminals must expire too; each input is checked separately.
        while True:
            await asyncio.sleep(5)
            if not await self._check_authorization():
                return

    async def start(self):
        """启动SSH代理会话"""
        from engines.device_adapter import get_device_mode
        from engines.device_lock import DeviceBusyError, acquire_device_lock
        if not await self._check_authorization():
            return
        watchdog = asyncio.create_task(self._watch_authorization()) if self._authorize else None
        try:
            if get_device_mode() == "sim":
                await self._start_sim_shell()
            else:
                async with acquire_device_lock(self.device_ip, self.ssh_port):
                    await self._start_ssh_session()
        except DeviceBusyError:
            await self._connection_error("busy", "设备正被其他任务使用。等当前操作结束后可重新连接。")
            await self.stop()
        finally:
            if watchdog:
                watchdog.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog
            await self.stop()

    async def _start_ssh_session(self):
        """SSH 连接与双向转发（调用方已持有设备锁）。"""
        try:
            logger.info("webssh_connecting", device_ip=self.device_ip, username=self.username)
            
            from engines.netmiko_exec import _run_ssh_operation, new_ssh_client
            self._ssh_client = new_ssh_client()
            settings = get_settings()
            timeout = settings.ssh_connect_timeout
            
            await _run_ssh_operation(lambda: connect_with_device_password(
                self._ssh_client, self.device_ip, self.ssh_port, self.username, self.password, timeout,
            ))
            if not await self._check_authorization():
                return
            logger.info("webssh_ssh_connected", device_ip=self.device_ip)

            # 创建交互式终端
            self._channel = await asyncio.to_thread(
                self._ssh_client.invoke_shell, term="xterm-256color", width=120, height=40,
            )
            self._channel.setblocking(0)
            self._running = True

            # 跳过路由器首次SSH密码修改提示
            await self._skip_password_change_prompt()

            # 发送连接成功消息
            await self.websocket.send_text(json.dumps({
                "type": "connected",
                "message": f"已连接到 {self.device_ip}"
            }))
            
            logger.info("webssh_session_started", device_ip=self.device_ip)
            
            # 启动双向数据转发
            await asyncio.gather(self._ws_to_ssh(), self._ssh_to_ws())
            
        except UnknownDeviceHost as exc:
            await self._connection_error("host_unknown", f"{exc}。请管理员核对指纹后登记。")
        except paramiko.BadHostKeyException:
            await self._connection_error("host_changed", "设备 SSH 主机密钥已变化。请管理员通过设备控制台核对后更新登记。")
        except InvalidKnownHosts as exc:
            await self._connection_error("known_hosts_invalid", str(exc))
        except paramiko.AuthenticationException as e:
            logger.error("webssh_auth_failed", device_ip=self.device_ip, error=str(e))
            await self._connection_error("authentication", "设备拒绝了 SSH 登录。请管理员检查这台设备的 SSH 账号、密码和登录权限。")
        except (TimeoutError, socket.timeout, paramiko.ssh_exception.NoValidConnectionsError) as e:
            logger.error("webssh_unreachable", device_ip=self.device_ip, error=str(e))
            await self._connection_error("unreachable", "未能连接设备的 SSH 端口。请确认设备已启动、管理地址可达，再检查 SSH 服务和端口。")
        except paramiko.SSHException as e:
            logger.error("webssh_ssh_error", device_ip=self.device_ip, error=str(e))
            await self._connection_error("handshake", "SSH 握手或终端初始化失败。请管理员检查设备 SSH 服务，并按本次时间查看终端日志。")
        except Exception as e:
            logger.error("webssh_start_failed", device_ip=self.device_ip, error=str(e))
            await self._connection_error("connection", "终端连接失败。请重新连接，若仍失败请管理员按本次时间查看终端日志。")
        finally:
            await self.stop()

    async def _connection_error(self, code: str, message: str):
        with suppress(Exception):
            await self.websocket.send_text(json.dumps({"type": "error", "code": code, "message": message}))

    async def _start_sim_shell(self):
        """模拟模式交互终端：脚本化 VRP 回显，不做任何网络连接。"""
        from engines.device_adapter import SimDeviceAdapter
        sim = SimDeviceAdapter(hostname=self.device_hostname, management_ip=self.device_ip)
        try:
            await self.websocket.send_text(json.dumps({
                "type": "connected",
                "message": f"已打开 {sim.hostname} 的模拟终端（本地只读）。输入 help 查看可用命令。",
            }))
        except Exception:
            return
        self._running = True
        prompt = f"<{sim.hostname}>"
        pending_line = ""
        after_cr = False
        line_too_long = False
        await self.websocket.send_text(json.dumps({"type": "output", "data": prompt}))
        try:
            while self._running:
                data = await self.websocket.receive_text()
                msg = json.loads(data)
                if not await self._check_authorization():
                    break
                if msg.get("type") != "input" or not isinstance(msg.get("data"), str):
                    continue
                output = []
                for char in _SIM_NAVIGATION_KEYS.sub("", msg["data"]):
                    paired_lf = after_cr and char == "\n"
                    after_cr = char == "\r"
                    if paired_lf:
                        continue
                    if char in "\r\n":
                        output.append("\r\n")
                        if line_too_long:
                            output.append("输入过长，命令未执行。请缩短后重试。\r\n")
                        elif pending_line.strip():
                            line = pending_line.strip()
                            response = await sim.run_command(line)
                            if response.startswith(prompt):
                                response = response.partition("\n")[2]
                            response = response.rstrip("\r\n")
                            if self.session_logger:
                                self.session_logger.log_input(line + "\n")
                                self.session_logger.log_output(response + "\n")
                            if response:
                                output.append(response + "\r\n")
                        output.append(prompt)
                        pending_line = ""
                        line_too_long = False
                    elif char == "\x03":
                        output.append("^C\r\n" + prompt)
                        pending_line = ""
                        line_too_long = False
                    elif char in "\x08\x7f":
                        if pending_line and not line_too_long:
                            pending_line = pending_line[:-1]
                            output.append("\b \b")
                    elif char.isprintable() and not line_too_long:
                        if len(pending_line) >= _SIM_MAX_COMMAND_LENGTH:
                            line_too_long = True
                        else:
                            pending_line += char
                            output.append(char)
                if output:
                    await self.websocket.send_text(json.dumps({"type": "output", "data": "".join(output)}))
        except WebSocketDisconnect:
            self._running = False
        except Exception as exc:
            logger.error("sim_shell_error", error=str(exc))
            self._running = False
        finally:
            await self.stop()

    async def _skip_password_change_prompt(self):
        """检测并跳过路由器首次SSH密码修改提示（Change now? [Y/N]）"""
        import time
        deadline = time.time() + 3  # 最多等3秒
        buf = ""
        while time.time() < deadline:
            if self._channel and self._channel.recv_ready():
                data = self._channel.recv(4096).decode("utf-8", errors="replace")
                buf += data
                # 检测密码修改提示
                if "Change now" in buf or "change your password" in buf.lower():
                    logger.info("webssh_skip_password_change", device_ip=self.device_ip)
                    self._channel.send(b"N\r")
                    await asyncio.sleep(0.3)
                    # 读取剩余提示输出并转发给前端
                    while self._channel.recv_ready():
                        extra = self._channel.recv(4096).decode("utf-8", errors="replace")
                        await self.websocket.send_text(json.dumps({"type": "output", "data": extra}))
                    return
                # 已进入正常shell提示符（#或>结尾），无需跳过
                if buf.rstrip().endswith("#") or buf.rstrip().endswith(">"):
                    # 把已读取的内容发给前端
                    await self.websocket.send_text(json.dumps({"type": "output", "data": buf}))
                    return
            else:
                await asyncio.sleep(0.05)
        # 超时未检测到提示，把已读取的内容发给前端
        if buf:
            await self.websocket.send_text(json.dumps({"type": "output", "data": buf}))

    async def _ws_to_ssh(self):
        """WebSocket -> SSH：转发用户输入"""
        try:
            while self._running:
                data = await self.websocket.receive_text()
                msg = json.loads(data)
                if not await self._check_authorization():
                    break
                if msg.get("type") == "input":
                    if self._channel:
                        self._channel.send(msg.get("data", "").encode("utf-8"))
                        if self.session_logger:
                            self.session_logger.log_input(msg.get("data", ""))
                elif msg.get("type") == "resize":
                    if self._channel:
                        self._channel.resize_pty(width=msg.get("cols", 120), height=msg.get("rows", 40))
        except WebSocketDisconnect:
            self._running = False
        except Exception as e:
            logger.error("ws_to_ssh_error", error=str(e))
            self._running = False

    async def _ssh_to_ws(self):
        """SSH -> WebSocket：转发设备输出"""
        loop = asyncio.get_running_loop()
        try:
            while self._running:
                if self._channel and self._channel.recv_ready():
                    data = await loop.run_in_executor(None, lambda: self._channel.recv(4096))
                    if data:
                        output = data.decode("utf-8", errors="replace")
                        await self.websocket.send_text(json.dumps({"type": "output", "data": output}))
                        if self.session_logger:
                            self.session_logger.log_output(output)
                    else:
                        break
                else:
                    await asyncio.sleep(0.05)
        except Exception as e:
            logger.error("ssh_to_ws_error", error=str(e))
        finally:
            self._running = False

    async def stop(self):
        """停止会话 - 确保SSH连接完全关闭"""
        self._running = False
        try:
            if self._channel and not self._channel.closed:
                self._channel.close()
        except Exception as e:
            logger.debug("channel_close_error", error=str(e))
        try:
            if self._ssh_client:
                transport = self._ssh_client.get_transport()
                if transport and transport.is_active():
                    transport.close()
                self._ssh_client.close()
        except Exception as e:
            logger.debug("ssh_close_error", error=str(e))
        try:
            if self.session_logger:
                self.session_logger.close()
        except Exception:
            pass
        logger.info("webssh_session_stopped", device_ip=self.device_ip)
