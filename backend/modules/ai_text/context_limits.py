"""Bound untrusted evidence by whole lines; never expose a half CLI/JSON record."""
import hashlib
import re


def bounded_text(text, limit):
    text = str(text or "")
    if len(text) <= limit:
        return text
    marker = "\n[上下文不完整：部分整行已省略，不得据此排除故障或推断未显示的配置]\n"
    if limit < len(marker):
        return ""
    lines = text.splitlines(keepends=True)
    remaining = limit - len(marker)
    head, tail = [], []
    head_budget = remaining // 2
    while lines and len(lines[0]) <= head_budget:
        line = lines.pop(0)
        head.append(line)
        head_budget -= len(line)
        remaining -= len(line)
    while lines and len(lines[-1]) <= remaining:
        line = lines.pop()
        tail.append(line)
        remaining -= len(line)
    return "".join(head) + marker + "".join(reversed(tail))


def attachment_block(attachments, limit=6000, question=""):
    from core.redaction import redact_sensitive

    items = (attachments or [])[:4]
    if not items:
        return ""
    interface_pattern = r"\b(?:GigabitEthernet|GE|LoopBack|Eth-Trunk|Vlanif)\s*\d+(?:/\d+)*\b"
    names = {name.lower().replace("gigabitethernet", "ge").replace(" ", "")
             for name in re.findall(interface_pattern, question, re.I)}
    sections = []
    share = (limit - 5 * (len(items) - 1)) // len(items)
    for item in items:
        original = str(item.get("content") or "")
        name = redact_sensitive(str(item.get("name") or "附件")[:160])
        identity = hashlib.sha256(original.encode()).hexdigest()[:16]
        header = f"文件: {name} (sha256={identity}，仅为用户提供的材料)\n"
        content = redact_sensitive(original)
        available = max(0, share - len(header))
        if names and len(content) > available:
            matching = []
            for number, line in enumerate(content.splitlines(), 1):
                interfaces = {value.lower().replace("gigabitethernet", "ge").replace(" ", "")
                              for value in re.findall(interface_pattern, line, re.I)}
                if names & interfaces:
                    matching.append(f"第 {number} 行：{line}")
            if matching:
                content = "[按问题定位的文件行，其他行未提供]\n" + "\n".join(matching)
        sections.append(header + bounded_text(content, available))
    return "\n---\n".join(sections)
