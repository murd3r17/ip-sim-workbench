"""Direct textbook definitions and purposes for simple named questions."""
import re


_PREFIX = r"(?:(?:请问|请解释|请简述)\s*)?(?:(?:教材|原书|课本)(?:里|中|上)?\s*)?"
_TOPIC = r"(?P<topic>[\u3400-\u9fffA-Za-z0-9_./+·\-– \t]{2,30}?)"
_REQUESTS = (
    ("principle_purpose", re.compile(rf"{_PREFIX}{_TOPIC}\s*(?:的作用是什么|有什么作用|有何作用|主要用途是什么|用于什么)")),
    ("principle_definition", re.compile(rf"{_PREFIX}{_TOPIC}\s*(?:的定义是什么|是什么|是什么意思|指的是什么|指什么)")),
    ("principle_definition", re.compile(rf"{_PREFIX}(?:什么是|何谓|请定义)\s*{_TOPIC}")),
)
_GENERIC = {"原理", "机制", "状态", "作用", "目标", "配置", "操作", "日志", "结果", "现象", "字段", "这个词"}
_QUERY_CONTEXT = re.compile(r"(?:这|那|该|上述)(?:次|一轮|份|项|个|项|里)|设备上|实机|真机|生产现场|前后|与|和|分别|以及|或|相比|两者")
_CONCRETE_CASE = re.compile(r"本例|例题|课件例|例如|为例|示例|本实验|该实验|此实验|图中|图上|截图|拓扑图|回显|读回|日志|命令行|"
                            r"用于说明|用于示意|练习(?:答案|题)|验证(?:步骤|结果)|目前|刚完成|预期|计划|应当|建议")
_LITERAL_COMMAND = re.compile(r"(?<![A-Za-z0-9_])(?:display|show|undo)\s+", re.I)
_CLAUSE = re.compile(r"[^。！？\r\n]+[。！？]?")
_LEADING_TITLE = re.compile(r"^\s*\*\*[^*\r\n]+\*\*\s*")
_DEFINITION = r"(?:通常|一般)?(?:是(?!否|如何|不是)|指(?:的是)?|属于|定义为|特指)"
_PURPOSE = r"(?:通常|一般|主要)?(?:用于|用以|用来|负责|作用是)"
_PARENTHESIS = r"(?:\s*[（(][^）)\n]{1,80}[）)])?"
_DECLARATIVE_PREFIX = r"(?:本章所讲\s*|[A-Za-z][A-Za-z0-9.]{1,8}\s+[0-9][A-Za-z0-9.\-]{1,18}\s*定义的\s*)?"


def principle_request(text: str) -> tuple[str, str] | None:
    for role, form in _REQUESTS:
        if match := form.fullmatch(text):
            subject = match["topic"].strip()
            if subject not in _GENERIC and not _QUERY_CONTEXT.search(subject) and any(letter.isalpha() for letter in subject):
                return role, subject
    return None


def multiple_principle_requests(query: str, clauses: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    if not 2 <= len(clauses) <= 3 or _CONCRETE_CASE.search(query):
        return ()
    requests = tuple(principle_request(clause) for clause in clauses)
    if any(request is None for request in requests):
        return ()
    named = tuple(request for request in requests if request is not None)
    if len({(kind, topic.casefold()) for kind, topic in named}) != len(named):
        return ()
    return named


def direct_principle(text: str, role: str, subject: str, *, separate_heading: bool = False) -> str | None:
    """Find one whole assertion with the requested term as its express subject."""
    relation = _DEFINITION if role == "principle_definition" else _PURPOSE
    subject_match = r"\s*".join(re.escape(word) for word in subject.split())
    matches = set()
    if separate_heading:
        text = _LEADING_TITLE.sub("", text)
    for span in _CLAUSE.finditer(text):
        statement = _LEADING_TITLE.sub("", span[0]).strip()
        if not 12 <= len(statement) <= 340 or _CONCRETE_CASE.search(statement) or _LITERAL_COMMAND.search(statement):
            continue
        if role == "principle_purpose" and re.search(r"[,，；;]", statement):
            continue
        pattern = rf"\A{_DECLARATIVE_PREFIX}{subject_match}{_PARENTHESIS}\s*{relation}\s*(?P<predicate>\S.*)\Z"
        if (match := re.match(pattern, statement, re.I)) and len(match["predicate"].rstrip("。；;")) >= 4:
            matches.add(statement)
    return next(iter(matches)) if len(matches) == 1 else None
