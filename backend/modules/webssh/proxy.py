"""WebSSH代理 - WebSocket与SSH之间的双向数据转发"""
import asyncio
import paramiko
import json
from contextlib import suppress
from typing import Awaitable, Callable
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from core.logger import get_logger
from core.config import get_settings

logger = get_logger("webssh")


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
        try:
            valid = await self._authorize()
        except Exception:
            valid = False
        if not valid:
            self._running = False
            with suppress(Exception):
                await self.websocket.send_text(json.dumps({"type": "error", "message": "登录状态已失效，请重新登录"}))
                await self.websocket.close(code=4001, reason="登录状态已失效")
            await self.stop()
        return valid

    async def _watch_authorization(self):
        # Idle terminals must expire too; each input is checked separately.
        while True:
            await asyncio.sleep(5)
            if not await self._check_authorization():
                return

    def _connect_keyboard_interactive(self, timeout: int):
        """使用keyboard-interactive认证连接（适用于华为路由器）"""
        import socket
        sock = socket.create_connection((self.device_ip, self.ssh_port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.connect()

        def handler(title, instructions, prompt_list):
            return [self.password] * len(prompt_list)

        transport.auth_interactive(self.username, handler)
        if not transport.is_authenticated():
            transport.close()
            raise paramiko.AuthenticationException("keyboard-interactive认证失败")
        # 用transport替换client的底层连接
        self._ssh_client._transport = transport

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
        except DeviceBusyError as e:
            try:
                await self.websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
            except Exception:
                pass
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
            
            from engines.netmiko_exec import new_ssh_client
            self._ssh_client = new_ssh_client()
            settings = get_settings()
            loop = asyncio.get_running_loop()
            
            # SSH连接 - 先尝试password，失败后用keyboard-interactive
            try:
                await loop.run_in_executor(None, lambda: self._ssh_client.connect(
                    hostname=self.device_ip, port=self.ssh_port,
                    username=self.username, password=self.password,
                    timeout=settings.ssh_connect_timeout,
                    allow_agent=False, look_for_keys=False
                ))
            except paramiko.AuthenticationException:
                # 路由器使用keyboard-interactive认证
                logger.info("webssh_kbi_fallback", device_ip=self.device_ip)
                await loop.run_in_executor(None, self._connect_keyboard_interactive, settings.ssh_connect_timeout)
            logger.info("webssh_ssh_connected", device_ip=self.device_ip)

            # 创建交互式终端
            self._channel = self._ssh_client.invoke_shell(term="xterm-256color", width=120, height=40)
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
            
        except paramiko.AuthenticationException as e:
            error_msg = f"SSH认证失败: {e}"
            logger.error("webssh_auth_failed", device_ip=self.device_ip, error=str(e))
            try:
                await self.websocket.send_text(json.dumps({"type": "error", "message": error_msg}))
            except Exception:
                pass
        except paramiko.SSHException as e:
            error_msg = f"SSH连接错误: {e}"
            logger.error("webssh_ssh_error", device_ip=self.device_ip, error=str(e))
            try:
                await self.websocket.send_text(json.dumps({"type": "error", "message": error_msg}))
            except Exception:
                pass
        except Exception as e:
            error_msg = f"连接失败: {e}"
            logger.error("webssh_start_failed", device_ip=self.device_ip, error=str(e))
            try:
                await self.websocket.send_text(json.dumps({"type": "error", "message": error_msg}))
            except Exception:
                pass
        finally:
            await self.stop()

    async def _start_sim_shell(self):
        """模拟模式交互终端：脚本化 VRP 回显，不做任何网络连接。"""
        from engines.device_adapter import SimDeviceAdapter
        sim = SimDeviceAdapter(hostname=self.device_hostname)
        try:
            await self.websocket.send_text(json.dumps({
                "type": "connected",
                "message": f"已连接到 {self.device_ip}（模拟终端 DEVICE_MODE=sim）",
            }))
        except Exception:
            return
        self._running = True
        await self.websocket.send_text(json.dumps({"type": "output", "data": f"<{sim.hostname}>"}))
        try:
            while self._running:
                data = await self.websocket.receive_text()
                msg = json.loads(data)
                if not await self._check_authorization():
                    break
                if msg.get("type") == "input":
                    line = (msg.get("data") or "").strip()
                    if self.session_logger:
                        self.session_logger.log_input(line)
                    if not line:
                        await self.websocket.send_text(json.dumps({"type": "output", "data": f"<{sim.hostname}>"}))
                        continue
                    resp = await sim.run_command(line)
                    if self.session_logger:
                        self.session_logger.log_output(resp + "\n")
                    await self.websocket.send_text(json.dumps({"type": "output", "data": resp + "\n" + f"<{sim.hostname}>"}))
                elif msg.get("type") == "resize":
                    pass  # 模拟终端忽略尺寸
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
