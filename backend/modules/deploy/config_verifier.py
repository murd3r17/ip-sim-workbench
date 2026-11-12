"""配置回读差异比较工具。"""

from __future__ import annotations

import difflib
import re


class UnsupportedRestoreError(ValueError):
    """The changed configuration has no reviewed automatic inverse."""


class ConfigVerifier:
    """阶段4只提供纯差异比较；状态、锁和审计均由 DeployService 受控处理。"""

    @staticmethod
    def compare(left: str, right: str, *, preserve_case: bool = False) -> dict[str, list[str]]:
        """返回可供页面、导出和 AI 报告复用的结构化差异。

        语义（P2-08：此前 ``changed`` 恒为空，等于永远只报告增删）：
        - ``added``：只出现在 right 的行；
        - ``removed``：只出现在 left 的行；
        - ``changed``：同一位置被替换的行，形如 ``"旧行 -> 新行"``。

        同一个 replace 区块内能配对的行走 ``changed``，多出来的行按方向进
        ``added``/``removed``，因此三类互不重复计数。
        """
        left_lines = ConfigVerifier._ordered_config(left, preserve_case=preserve_case)
        right_lines = ConfigVerifier._ordered_config(right, preserve_case=preserve_case)
        matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines, autojunk=False)

        added: list[str] = []
        removed: list[str] = []
        changed: list[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag == "replace":
                paired = min(i2 - i1, j2 - j1)
                for offset in range(paired):
                    changed.append(f"{left_lines[i1 + offset]} -> {right_lines[j1 + offset]}")
                removed.extend(left_lines[i1 + paired:i2])
                added.extend(right_lines[j1 + paired:j2])
            elif tag == "delete":
                removed.extend(left_lines[i1:i2])
            else:  # insert
                added.extend(right_lines[j1:j2])

        return {
            "added": sorted(added),
            "removed": sorted(removed),
            "changed": sorted(changed),
        }

    @staticmethod
    def _compare_config(expected: str, actual: str) -> str | None:
        """Verify an incremental intent within its VRP view, not anywhere on the device."""
        missing = ConfigVerifier._missing_state(ConfigVerifier._state(expected), ConfigVerifier._state(actual))
        return f"缺失或不一致配置: {missing}" if missing else None

    @staticmethod
    def verify_snapshot(expected: str, actual: str) -> str | None:
        """Snapshot restoration requires both directions, including unwanted residue."""
        wanted, observed = ConfigVerifier._state(expected), ConfigVerifier._state(actual)
        missing = ConfigVerifier._missing_state(wanted, observed, snapshot=True)
        extra = ConfigVerifier._missing_state(observed, wanted, snapshot=True)
        return f"缺失或不一致配置: {missing}; 残留配置: {extra}" if missing or extra else None

    @staticmethod
    def _command(line: str) -> str:
        words = line.split()
        # Keep operands (descriptions, names and secrets) case-sensitive.
        words[0] = words[0].lower()
        if words[0] == "undo" and len(words) > 1:
            words[1] = words[1].lower()
        return " ".join(words)

    @staticmethod
    def _view(line: str) -> tuple[str, str] | None:
        words = line.split()
        head = words[0].lower()
        if head == "interface":
            # Some VRP fragments separate the type and port number with a space.
            # Dropping the latter merges all such interfaces into one context.
            return "root", " ".join(words).lower()
        if head in {"ospf", "bgp", "isis", "vlan", "aaa", "user-interface", "acl", "route-policy"}:
            count = 1 if head == "aaa" else 2
            key = " ".join(words[:count])
            return "root", key
        if line.lower().startswith("ip vpn-instance "):
            return "root", " ".join(words[:3])
        if head in {"area", "ipv4-family", "ipv6-family"}:
            return "child", " ".join(words)
        return None

    @staticmethod
    def _state(text: str) -> dict[tuple[str, ...], set[str]]:
        """Read explicit navigation and indented running-config blocks.

        Common VRP views also work for unindented command fragments. Unknown
        indented blocks keep their full path rather than flattening their leaves.
        """
        state: dict[tuple[str, ...], set[str]] = {(): set()}
        stack: list[tuple[str, int]] = []
        lines = text.splitlines()
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            if not stripped or stripped.startswith("!"):
                continue
            if stripped.startswith("#"):
                stack.clear()
                continue
            if re.match(r"^[<\[].+[>\]](?:display\b.*)?$", stripped, re.IGNORECASE):
                continue
            line = ConfigVerifier._command(stripped)
            lower = line.lower()
            if lower in {"system-view", "return"}:
                stack.clear()
                continue
            if lower == "quit":
                if stack:
                    stack.pop()
                continue
            if lower == "commit":
                continue
            indent = len(raw) - len(raw.lstrip())
            view = ConfigVerifier._view(line)
            if view and view[0] == "root":
                stack.clear()
            elif view and view[0] == "child":
                stack = stack[:1]
            elif indent:
                while stack and stack[-1][1] >= indent:
                    stack.pop()
            elif lower.startswith("sysname "):
                stack.clear()
            path = tuple(key for key, _ in stack)
            state.setdefault(path, set()).add(line)
            next_line = next((item for item in lines[index + 1:] if item.strip()), "")
            inferred_view = bool(next_line and len(next_line) - len(next_line.lstrip()) > indent)
            if view or inferred_view:
                key = view[1] if view else line
                stack.append((key, indent))
                state.setdefault(tuple(item[0] for item in stack), set())
        return state

    @staticmethod
    def _missing_state(expected: dict, actual: dict, *, snapshot: bool = False) -> list[str]:
        missing = []
        for path, commands in expected.items():
            observed = actual.get(path, set())
            for command in commands:
                # Snapshot equivalence must not infer arbitrary undo semantics.
                known_default = (
                    command == "undo shutdown" and len(path) == 1 and path[0].startswith("interface ")
                ) or (not path and command == "undo lldp enable")
                if command.startswith("undo ") and (not snapshot or known_default):
                    positive = command[5:]
                    present = not any(item == positive or item.startswith(positive + " ") for item in observed)
                else:
                    present = command in observed
                    # A view opened without optional settings still exists when
                    # running-config appends settings (e.g. ospf 1 router-id ...).
                    if not snapshot and not present and ConfigVerifier._view(command):
                        present = any(item.startswith(command + " ") for item in observed)
                if not present:
                    missing.append(f"{' / '.join(path) or 'system'}: {command}")
        return sorted(missing)

    @staticmethod
    def raise_on_cli_error(output: str | None) -> None:
        if re.search(r"(?im)^\s*(?:error\s*:|failure\s*:|%\s|unrecognized command|wrong parameter|incomplete command|too many parameters|ambiguous command)", output or ""):
            raise ValueError("设备拒绝配置命令，未确认配置生效")

    @staticmethod
    def build_restore_commands(current: str, target: str) -> list[str]:
        """Plan only inverses we can justify; unchanged opaque config is untouched.

        Supported: sysname, global LLDP enable, existing-interface description/IP/shutdown, and
        LoopBack creation/removal. Physical ports, routing/security policies and
        unknown changed commands require a reviewed manual restoration.
        """
        if ConfigVerifier.verify_snapshot(target, current) is None:
            return []
        before, after = ConfigVerifier._state(current), ConfigVerifier._state(target)
        root_commands: list[str] = []
        interface_commands: dict[tuple[str, ...], list[str]] = {}
        removed_paths = set(before) - set(after)
        added_paths = set(after) - set(before)

        def refuse() -> None:
            raise UnsupportedRestoreError("当前差异包含暂不支持自动恢复的配置，请人工核对快照差异")

        def loopback(path: tuple[str, ...]) -> bool:
            return len(path) == 1 and bool(re.fullmatch(r"interface loopback\d+", path[0], re.IGNORECASE))

        for path in sorted(removed_paths):
            if not loopback(path):
                refuse()
            root_commands.append("undo " + path[0])
        for path in sorted(added_paths):
            if not loopback(path):
                refuse()
            interface_commands[path] = []

        for path in sorted(set(before) | set(after)):
            if path in removed_paths:
                continue
            old, wanted = before.get(path, set()), after.get(path, set())
            extra, missing = old - wanted, wanted - old
            if not extra and not missing:
                continue
            if not path:
                for line in sorted(extra):
                    view = ConfigVerifier._view(line)
                    if view and (view[1],) in removed_paths:
                        continue
                    if line.startswith("sysname ") and any(item.startswith("sysname ") for item in wanted):
                        continue  # sysname replaces its previous value
                    if line == "lldp enable":
                        root_commands.append("undo lldp enable")
                        continue
                    if line == "undo lldp enable":
                        continue  # explicit disabled state and default absence are equivalent
                    refuse()
                for line in sorted(missing):
                    view = ConfigVerifier._view(line)
                    if view and (view[1],) in added_paths:
                        continue
                    if line in {"lldp enable", "undo lldp enable"}:
                        if line not in root_commands:
                            root_commands.append(line)
                        continue
                    if not line.startswith("sysname "):
                        refuse()
                    root_commands.append(line)
                continue
            if len(path) != 1 or not path[0].startswith("interface "):
                refuse()
            commands = interface_commands.setdefault(path, [])
            for line in sorted(extra):
                if line.startswith("description "):
                    if not any(item.startswith("description ") for item in wanted):
                        commands.append("undo description")
                elif line.startswith("ip address ") or line == "shutdown":
                    commands.append("undo " + line)
                elif line == "undo shutdown":
                    continue  # absence and explicit 'undo shutdown' have the same state
                else:
                    refuse()
            for line in sorted(missing):
                if not (line.startswith(("description ", "ip address ")) or line in {"shutdown", "undo shutdown"}):
                    refuse()
                if line not in commands:
                    commands.append(line)
        for path, commands in sorted(interface_commands.items()):
            root_commands.extend([path[0], *commands, "quit"])
        return root_commands

    @staticmethod
    def build_incremental_restore_commands(current: str, intent: str) -> list[str]:
        """Preflight the same bounded inverse set before applying an incremental intent.

        Preserve untouched opaque settings. Never infer inverses for routing, AAA,
        interface LLDP or arbitrary `undo` commands. This is not a VRP interpreter.
        """
        before, change = ConfigVerifier._state(current), ConfigVerifier._state(intent)
        reverse: list[str] = []

        def refuse():
            raise UnsupportedRestoreError("写入前无法建立受支持的恢复计划，已拒绝配置")

        # Commit/save belong to the execution lifecycle, never a submitted payload.
        if any(re.match(r"^(?:commit|save)\b", line.strip(), re.I) for line in intent.splitlines()):
            refuse()
        for command in change.get((), set()):
            if command.startswith("interface "):
                path = (command.lower(),)
                if path not in before and not re.fullmatch(r"interface loopback\d+", command, re.I):
                    refuse()
            elif command.startswith("sysname "):
                old = [line for line in before.get((), set()) if line.startswith("sysname ")]
                if len(old) != 1:
                    refuse()
                reverse.extend(old)
            elif command in {"lldp enable", "undo lldp enable"}:
                inverse = "lldp enable" if "lldp enable" in before.get((), set()) else "undo lldp enable"
                if inverse not in reverse:
                    reverse.append(inverse)
            else:
                refuse()
        for path, commands in change.items():
            if not path:
                continue
            if len(path) != 1 or not path[0].startswith("interface "):
                refuse()
            old = before.get(path, set())
            restores: list[str] = []
            for command in sorted(commands):
                if command.startswith("description ") or command == "undo description":
                    descriptions = [line for line in old if line.startswith("description ")]
                    if len(descriptions) > 1:
                        refuse()
                    restores.extend(descriptions or ["undo description"])
                elif command in {"shutdown", "undo shutdown"}:
                    restores.append("shutdown" if "shutdown" in old else "undo shutdown")
                elif command.startswith("ip address ") or command == "undo ip address" or command.startswith("undo ip address "):
                    if command.startswith("ip address ") and command not in old:
                        restores.append("undo " + command)
                    restores.extend(sorted(line for line in old if line.startswith("ip address ")))
                else:
                    refuse()
            if path not in before:
                if not re.fullmatch(r"interface loopback\d+", path[0], re.I):
                    refuse()
                reverse.append("undo " + path[0])
            elif restores:
                reverse.extend([path[0], *dict.fromkeys(restores), "quit"])
        return reverse

    @staticmethod
    def _normalize_config(config_text: str) -> set[str]:
        """去除注释、空行和无关空白后进行不区分大小写比较（集合语义）。"""
        return set(ConfigVerifier._ordered_config(config_text))

    @staticmethod
    def _ordered_config(config_text: str, *, preserve_case: bool = False) -> list[str]:
        """与 ``_normalize_config`` 同样的清洗规则，但保留顺序与重复行，供差异对齐使用。"""
        lines: list[str] = []
        for line in config_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                continue
            normalized = " ".join(stripped.split())
            lines.append(normalized if preserve_case else normalized.lower())
        return lines
