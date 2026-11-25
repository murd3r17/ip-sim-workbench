"""Match original setup, first record and follow-up evidence from a named exercise."""

from dataclasses import dataclass
import re

from core.source_units import reading_units

from .query_focus import compact_text


_NAMED = re.compile(r"^(?:同一(?:次|个)|这项|教材中)?(?P<name>[\w ·-]{4,28}?(?:练习|实验|案例|演练))"
                    r"(?:里|中|内)?\s*[，,：:]\s*(?P<setup>.+)$")
_LOOKUP = re.compile(r"PDF\s*第|第\s*\d+\s*页|逐字|原句|现场|执行命令|接入设备", re.I)
_SETUP_ACTIONS = {
    "登记": r"登记|录入|填入|记入|写入",
    "录入": r"登记|录入|填入|记入|写入",
    "写入": r"登记|录入|填入|记入|写入",
    "填入": r"登记|录入|填入|记入|写入",
    "设置": r"设定|设置|配置",
    "配置": r"设定|设置|配置",
    "保存": r"保存|归档|存入",
}
_SETUP_QUESTION = re.compile(r"^(?P<object>[\w-]{2,32}?)(?:是)?(?:在)?哪(?:一|个)?(?:步(?:骤)?|阶段|环节)"
                             rf"(?:进行|完成|做了|才)?(?P<action>{'|'.join(_SETUP_ACTIONS)})(?:的|呢)?$")
_FIRST = r"(?:首份|首张|第一次|第一份|第一张|最早(?:的|那份|那张)?|首次)"
_ARTIFACT = r"(?:抄表|回显|读回|读数表|测量表|观察表|记录表|状态表|输出|表格|记录)"
_FIRST_QUESTION = re.compile(rf"{_FIRST}\s*(?:的|已完成的)?\s*(?P<artifact>{_ARTIFACT}).*"
                             r"(?:哪(?:一)?(?:栏|项|列|个|条)|什么|多少)")
_REVIEW_QUESTION = re.compile(r"(?:后来|之后|后续|随后|再)(?:是)?(?:拿|用|以|靠|对照|参考|查)"
                              r".{0,3}(?:什么|哪(?:一|个|种|份|张)?).{0,15}(?:记录|表|日志|台账|材料|单)"
                              r".{0,8}(?:复查|复核|核对|对照|校验)")
_TITLE_PREFIX = re.compile(r"^(?:(?:案例|实验|任务|练习)\s*\d+[\s、.:：-]+|\d+(?:[.．]\d+)*[.．、\s]+)\s*")
_NUMBERED_STEP = re.compile(r"^#+\s*步骤\s*[0-9一二三四五六七八九十]+[\s、.:：-]+\S.*$")
_PLAN_ONLY = re.compile(r"预计|预期|计划|打算|准备|模板|预填|将要|将来|如果|假如|应(?:当|填写|写入)|"
                        r"建议|请(?:记录|填|写|用|复查|复核)|待(?:测|查|复核|复查|核对)|"
                        r"(?:尚|仍|还|并)?未(?:作|做|见|完成|登记|读|查|核|复查)|没有(?:做|用|复查|核对)|另(?:一|个)(?:次|组|例|实验)")
_FIRST_WRITTEN = re.compile(r"写了|(?:已写入|写入了)|填了|(?:已填入|填入了)|记了|记下了|记入了|记录了|"
                             r"记录为|读到|读出|看到|显示|保留了")
_ACTUAL_CHECK = re.compile(r"复查时|复核时|核对时|随后的复查|后来实际|已(?:使用|完成|进行)复查|"
                           r"随后(?:用|拿|取)|后来(?:用|拿|取)|复查已完成")
_REVIEW_MATERIAL = re.compile(r"(?:用|拿|取|对照|按|依据)(?P<material>[^，。；！？,]{3,35}?(?:表|日志|台账|记录|单|卡|材料))"
                              r"(?:来|实际|重新|再次)?(?:同|与|和)?\s*(?:复查|复核|核对|对照|校验)")


@dataclass(frozen=True)
class RecordSequence:
    scope: str
    setting: str
    action: str
    artifact: str


def record_sequence_request(query: str, clauses: tuple[str, ...]) -> RecordSequence | None:
    """Accept three separately asked duties with an explicitly named original exercise."""
    if len(clauses) != 3 or _LOOKUP.search(query) or _PLAN_ONLY.search(query):
        return None
    named = _NAMED.fullmatch(clauses[0])
    setup = _SETUP_QUESTION.fullmatch(named["setup"]) if named else None
    first = _FIRST_QUESTION.search(clauses[1])
    if not (setup and first and _REVIEW_QUESTION.search(clauses[2])):
        return None
    return RecordSequence(compact_text(named["name"]), compact_text(setup["object"]), setup["action"], first["artifact"])


def case_title(title: str) -> str:
    return compact_text(_TITLE_PREFIX.sub("", title).strip())


def _first_record(text, artifact):
    prefix = re.search(rf"{_FIRST}\s*(?:已完成的)?\s*{re.escape(artifact)}", text)
    if not prefix:
        return False
    for line in re.split(r"[。；！？\n]", text[prefix.start():]):
        assertion = _FIRST_WRITTEN.search(line)
        if re.search(re.escape(artifact), line) and assertion and len(compact_text(line[assertion.end():])) >= 2:
            return True
    return False


def sequence_witnesses(request: RecordSequence, body: str):
    """Yield original paragraph ranges with independently stated evidence duties."""
    units = reading_units(body)
    for number, unit in enumerate(units):
        if unit.kind != "paragraph" or unit.end - unit.start > 1080:
            continue
        text = body[unit.start:unit.end].strip()
        if _PLAN_ONLY.search(text):
            continue
        if number and request.setting in compact_text(text) and re.search(_SETUP_ACTIONS[request.action], text):
            previous = units[number - 1]
            if previous.kind == "heading" and _NUMBERED_STEP.fullmatch(body[previous.start:previous.end].strip()):
                yield 1, text, body[previous.start:unit.end].strip()
        if _first_record(text, request.artifact):
            yield 2, text, text
        if (_ACTUAL_CHECK.search(text) and re.search(rf"{_FIRST}\s*(?:的)?\s*{re.escape(request.artifact)}", text)
                and (material := _REVIEW_MATERIAL.search(text)) and request.artifact not in material["material"]):
            yield 3, text, text
