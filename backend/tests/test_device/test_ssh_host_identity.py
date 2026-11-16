"""Use disposable loopback SSH servers to check identity before credentials."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import socket
from threading import Event

import paramiko
import pytest

from core.config import get_settings
from engines.ssh_trust import (
    InvalidKnownHosts, UnknownDeviceHost, connect_with_device_password, new_ssh_client,
)


class FixtureAuthentication(paramiko.ServerInterface):
    def __init__(self, calls, interactive):
        self.calls = calls
        self.interactive = interactive

    def get_allowed_auths(self, username):
        return "password,keyboard-interactive"

    def check_auth_password(self, username, password):
        self.calls.append("password")
        return paramiko.AUTH_FAILED if self.interactive else paramiko.AUTH_SUCCESSFUL

    def check_auth_interactive(self, username, submethods):
        self.calls.append("interactive")
        query = paramiko.InteractiveQuery()
        query.add_prompt("Password", echo=False)
        return query

    def check_auth_interactive_response(self, responses):
        return paramiko.AUTH_SUCCESSFUL if len(responses) == 1 else paramiko.AUTH_FAILED


@contextmanager
def local_ssh(key, *, interactive=False):
    calls = []
    stop = Event()
    with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as pool:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(4)

        def serve():
            connection, _ = listener.accept()
            with paramiko.Transport(connection) as transport:
                transport.add_server_key(key)
                try:
                    transport.start_server(server=FixtureAuthentication(calls, interactive))
                except (EOFError, ConnectionResetError, ConnectionAbortedError):
                    return  # A rejecting client can close as the server finishes its handshake.
                stop.wait(timeout=5)

        worker = pool.submit(serve)
        try:
            yield listener.getsockname()[1], calls
        finally:
            stop.set()
            worker.result(timeout=6)


@pytest.mark.parametrize("case", ["unknown", "changed", "registered", "compatibility"])
def test_ssh_host_identity_before_authentication(tmp_path, monkeypatch, case):
    host_key = paramiko.RSAKey.generate(2048)
    monkeypatch.setenv("SSH_STRICT_HOST_KEY", "false" if case == "compatibility" else "true")
    with local_ssh(host_key, interactive=case == "registered") as (port, calls):
        if case in {"registered", "changed"}:
            pinned = host_key if case == "registered" else paramiko.RSAKey.generate(2048)
            path = tmp_path / "known_hosts"
            path.write_text(f"[127.0.0.1]:{port} {pinned.get_name()} {pinned.get_base64()}\n", encoding="utf-8")
            monkeypatch.setenv("SSH_KNOWN_HOSTS", str(path))
        get_settings.cache_clear()
        with new_ssh_client() as client:
            connect = lambda: connect_with_device_password(client, "127.0.0.1", port, "fixture", "", 3)
            if case == "unknown":
                with pytest.raises(UnknownDeviceHost, match="SHA256:"):
                    connect()
            elif case == "changed":
                with pytest.raises(paramiko.BadHostKeyException):
                    connect()
            else:
                connect()
        expected = ["password", "interactive"] if case == "registered" else ["password"] if case == "compatibility" else []
        assert calls == expected


@pytest.mark.parametrize("content", [None, "", "not a host key\n", "host ssh-invalid YQ==\n"])
def test_explicit_invalid_known_hosts_stops_connection(tmp_path, monkeypatch, content):
    path = tmp_path / "known_hosts"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("SSH_KNOWN_HOSTS", str(path))
    with pytest.raises(InvalidKnownHosts):
        new_ssh_client()
