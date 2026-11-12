"""Stateful protected-interface output scan shared by all product transports.

The independent evaluation oracle lives separately in backend/evaluation.
Complete clauses/CLI lines are inspected before publication; token boundaries
never determine whether a command is safe.
"""
import re

DEFAULT_PROTECTED = ("GigabitEthernet0/0/0", "Mgmt0/0/0", "MEth0/0/1")
NAME = r"(?:XGigabit\s*Ethernet|Gigabit\s*Ethernet|XGE|GE|Ethernet|Eth|Mgmt|MEth|LoopBack|Vlanif|Vlan)\s*\d+(?:[/.:\-]\d+)*"
MENTION = re.compile(rf"(?<![\w/])({NAME})(?![\w/])", re.I)
HEAD = re.compile(rf"^interface\s+({NAME})(?=$|\s|;)(.*)$", re.I)
BARE_HEAD = re.compile(rf"^({NAME})\s+(.+)$", re.I)
EXIT = re.compile(r"^(?:quit|exit|return|#|!)$", re.I)
READ = re.compile(r"^(?:display|ping|tracert)\b", re.I)
WRITE = re.compile(r"\b(?:shutdown|undo\s+\S+|ip(?:v6)?\s+address|description|port\s+\S+|ospf\s+enable|isis\s+enable|traffic-filter|qos|stp|reset|reboot|format|delete|commit|save)\b", re.I)
PROPOSE = re.compile(r"执行|运行|输入|下发|配置|关闭|\b(?:run|execute|enter|apply|then)\b", re.I)
NEGATION = re.compile(r"不会|不能|拒绝|无法|未生成|禁止|不允许|不可|不代|不提供|不建议|不要|勿|\b(?:do not|don't|never|cannot|must not|no modification)\b", re.I)
EXPLANATION = re.compile(r"^(?:description|shutdown|ip address)\s*(?:命令|是|表示|用于|means\b)", re.I)
NEGATED_ACTION = re.compile(
    rf"(?:不会|不能|拒绝|无法|禁止|不允许|不可|不建议|不要|勿|不)\s*(?:直接|擅自|尝试)?\s*(?:(?:对|在|为)\s*(?:接口\s*)?(?:{NAME}|管理口|保护口)\s*)?(?:执行|运行|输入|下发|配置|关闭|修改|更改|操作|生成|提供|shutdown|undo|ip address)"
    r"|\b(?:do not|don't|never|cannot|must not)\s+(?:run|execute|enter|apply|modify|change|shut|shutdown|use)\b", re.I)


def negated_writes(text):
    writes = list(WRITE.finditer(text))
    # An undo argument may touch Chinese punctuation without whitespace. Never
    # use its greedy end offset to decide which preceding clause negates it.
    return bool(writes) and all(NEGATED_ACTION.search(
        re.split(r"[,，;；。！？]|但是|然而|不过|但|然后|\b(?:but|however|then)\b",
                 text[:write.start()], flags=re.I)[-1]
        + re.match(r"[a-z-]+", text[write.start():], re.I)[0]) for write in writes)
# Whitespace after English sentence punctuation is part of the complete unit;
# dots inside IPv4/interface names never form a boundary.
BOUNDARY = re.compile(r"\n|[。！？；;，,]|(?<=[.!?])\s")


def normalize(name):
    name = re.sub(r"\s+", "", name).lower()
    for prefix, alias in (("xgigabitethernet", "xge"), ("gigabitethernet", "ge"), ("ethernet", "eth")):
        if name.startswith(prefix):
            return alias + name[len(prefix):]
    return name


class OutputScanner:
    def __init__(self, protected=None, *, structured=False):
        self.protected = {normalize(p) for p in [*DEFAULT_PROTECTED, *(protected or [])]}
        self.structured = structured
        self.current = None
        self.fenced = False
        self.reason = ""
        self.buffer = ""

    def block(self, raw, interface):
        self.reason = self.reason or f"保护口 {interface} 不允许生成写命令草稿；请改为只读核对并走变更审批。"
        suffix = "\r\n" if raw.endswith("\r\n") else "\n" if raw.endswith("\n") else ""
        return f"# 已阻止：保护口 {interface} 的写命令未生成" + suffix

    def unit(self, raw):
        text = raw.strip().rstrip(";；").strip()
        if not text:
            return raw
        if text.startswith("```"):
            self.fenced = not self.fenced
            self.current = None
            return raw
        # Strip a displayed device prompt only for classification.
        text = re.sub(r"^\[[^]\n]+\]\s*", "", text)
        if EXIT.fullmatch(text):
            self.current = None
            return raw
        if text.startswith(("#", "!")):
            return raw  # a comment does not escape a protected CLI context
        head = HEAD.fullmatch(text)
        if head:
            iface, rest = head[1], head[2].strip()
            if not rest:
                self.current = iface
                return raw
            if normalize(iface) in self.protected and (self.structured or self.fenced or WRITE.search(rest)):
                return self.block(raw, iface)
            if self.structured:
                self.current = iface
            return raw  # e.g. "interface GE... 的说明见文档"
        if self.current and normalize(self.current) in self.protected:
            if READ.match(text):
                return raw
            if self.structured or self.fenced:
                return self.block(raw, self.current)
            if WRITE.match(text) and not EXPLANATION.match(text) and not NEGATION.search(text):
                return self.block(raw, self.current)
            # Outside fenced/structured CLI, clear only on identifiable prose,
            # never on empty lines or a count of words in a command.
            if re.search(r"[。！？]|\b(?:explanation|means|read-only)\b", text, re.I) or NEGATION.search(text):
                self.current = None
            else:
                return self.block(raw, self.current)
        named = [m[1] for m in MENTION.finditer(text) if normalize(m[1]) in self.protected]
        bare = BARE_HEAD.fullmatch(text)
        executable_inline = bool(bare and WRITE.match(bare[2]))
        if named and WRITE.search(text) and (PROPOSE.search(text) or executable_inline) and not negated_writes(text):
            return self.block(raw, named[0])
        return raw

    def feed(self, text):
        self.buffer += text
        emitted = []
        while True:
            match = next((m for m in BOUNDARY.finditer(self.buffer)
                          if (m[0] not in {";", "；"} or not MENTION.search(self.buffer[:m.end()])
                              or HEAD.fullmatch(self.buffer[:m.end()].strip().rstrip(";；")))
                          and (m[0] not in {",", "，"} or (
                              not self.current and not self.fenced
                              and not MENTION.search(self.buffer[:m.end()])
                              and not WRITE.search(self.buffer[:m.end()])
                              and "`" not in self.buffer[:m.end()]))), None)
            if match is None:
                break
            unit, self.buffer = self.buffer[:match.end()], self.buffer[match.end():]
            emitted.append(self.unit(unit))
        return "".join(emitted)

    def flush(self):
        tail, self.buffer = self.buffer, ""
        return self.unit(tail) if tail else ""
