"""Bound untrusted evidence by whole lines; never expose a half CLI/JSON record."""
import hashlib


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


def attachment_block(attachments, limit=6000):
    blocks = []
    for item in (attachments or [])[:4]:
        content = str(item.get("content") or "")
        name = str(item.get("name") or "附件")[:160]
        identity = hashlib.sha256(content.encode()).hexdigest()[:16]
        blocks.append(f"文件: {name} (sha256={identity}，仅为用户提供的材料)\n{content}")
    return bounded_text("\n---\n".join(blocks), limit)
