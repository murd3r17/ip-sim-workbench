"""Windows process ownership. Never terminate by name, port, or a PID alone."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess


def kernel():
    if os.name != 'nt':
        raise RuntimeError('This local development launcher requires Windows')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    return k


def open_process(k, pid: int, *, terminate=False):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid process identifier')
    handle = k.OpenProcess(0x1000 | 0x100000 | (1 if terminate else 0), False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # No such PID. Access denied is NOT interpreted as dead.
            return None
        raise ctypes.WinError(error)
    return handle


def handle_identity(k, handle) -> dict:
    times = [wintypes.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
        raise ctypes.WinError(ctypes.get_last_error())
    buf = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buf))
    if not k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'created_ticks': (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime,
            'executable': os.path.normcase(buf.value)}


def powershell_json(script: str):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, encoding='utf-8', errors='strict', timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Process metadata query failed')
    return json.loads(result.stdout) if result.stdout.strip() else None


def snapshot(pid: int) -> dict | None:
    k = kernel()
    handle = open_process(k, pid)
    if handle is None:
        return None
    try:
        if k.WaitForSingleObject(handle, 0) == 0:
            return None
        info = handle_identity(k, handle)
        meta = powershell_json(
            "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
            f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' | "
            'Select-Object CommandLine,ParentProcessId | ConvertTo-Json -Compress')
        if k.WaitForSingleObject(handle, 0) == 0:
            return None
        if not meta or not meta.get('CommandLine'):
            raise RuntimeError('Missing process command line; ownership is unknown')
        return dict(info, pid=pid, command=meta['CommandLine'], parent_pid=meta['ParentProcessId'])
    finally:
        k.CloseHandle(handle)


def same_process(expected: dict, actual: dict | None) -> bool:
    fields = ('pid', 'created_ticks', 'executable', 'command')
    return bool(actual and all(expected.get(f) for f in fields)
                and all(expected[f] == actual.get(f) for f in fields))


def check_record(record: dict, launch_id: str, run_dir: Path, tool: Path) -> None:
    if type(record.get('pid')) is not int or type(record.get('created_ticks')) is not int:
        raise ValueError('Missing exact PID/creation time')
    command = record.get('command', '')
    if not record.get('executable') or launch_id not in command:
        raise ValueError('Process command is not bound to this launch')
    if record.get('kind') in ('backend', 'launcher'):
        if str(run_dir) not in command or str(tool) not in command or '_worker' not in command:
            raise ValueError('Backend process is not bound to this run directory')
    elif record.get('kind') == 'frontend':
        if f'isolated-{launch_id}' not in command or 'vite' not in command:
            raise ValueError('Frontend command is not bound to this launch')
    else:
        raise ValueError('Unknown owned process kind')


def stop_verified(record: dict) -> str:
    """Recheck full identity, then check ticks/exe on the very handle we terminate."""
    current = snapshot(record['pid'])
    if current is None:
        return 'already_exited'
    if not same_process(record, current):
        return 'refused_identity_mismatch'
    k = kernel()
    handle = open_process(k, record['pid'], terminate=True)
    if handle is None:
        return 'already_exited'
    try:
        actual = handle_identity(k, handle)
        if any(actual[f] != record[f] for f in ('created_ticks', 'executable')):
            return 'refused_identity_mismatch'
        if k.WaitForSingleObject(handle, 0) == 0:
            return 'already_exited'
        if not k.TerminateProcess(handle, 0):
            return 'failed_termination'
        return 'stopped' if k.WaitForSingleObject(handle, 5000) == 0 else 'failed_wait'
    finally:
        k.CloseHandle(handle)


def listener_pids(port: int) -> set[int]:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid local development port')
    data = powershell_json(f'@(Get-NetTCPConnection -LocalPort {port} -State Listen '
                           '-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess) '
                           '| ConvertTo-Json -Compress')
    return set(data if isinstance(data, list) else [data]) if data is not None else set()
