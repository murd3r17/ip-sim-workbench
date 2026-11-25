"""Ground a question about what a textbook observation can establish."""
import re

from .query_focus import compact_text


_TARGET = r"(?P<target>[^，,。；;？！?！]{2,36})"
_CHECK_TARGET = r"(?P<target>[^，,。；;？！?！]{2,36}?)"
_PROOF = r"(?:证明|说明|认定|确认|判断|判定|断定|确定|验收)"
_CAN = r"(?:能否|能不能|可不可以|可否|可以|能|是否能|够不够|足够|足不足以|足以)"
_SIGN_OFF = r"(?:打勾|画勾|划勾|勾选|填为通过|标为通过|记为通过)"
_CHECK_ITEM = r"(?:(?:这)?(?:一|两|三|[123])?[项栏](?:都|均|全|分别)?|上)"
_QUOTED_CLAIM = re.compile(r"“([^”\n]+)”|‘([^’\n]+)’|「([^」\n]+)」|『([^』\n]+)』|\"([^\"\n]+)\"")
_JOINT_CHECK = re.compile(rf"(?:(?:两|三|[23])项|这(?:些|几)项).{{0,12}}{_SIGN_OFF}"
                          rf"|(?:都|均|一起|分别).{{0,6}}{_SIGN_OFF}")
_ARTIFACT_MEASUREMENT = re.compile(
    r"(?:单凭|只凭|单看|只看)?(?:这份|这张|这个|这次|该|上述)\s*"
    r"(?:回显|读回|输出|日志|记录|图例|原图|表格?|截图|抓包)(?:中|里)?"
    r"(?:还|也)?(?:能不能|能否|能|可不可以|可以)(?:顺带|顺便|直接|单独)?"
    r"(?:给(?:我|出)?|显示|看到|读出|量出|测出|得出)\s*"
    r"(?P<target>[^，,。；;？！?！]{3,34}?(?:计时|耗时|持续时间|恢复时间|中断时长|用时|秒数|时长))[吗呢]?(?=[。？！?!；;]|$)"
)
_ARTIFACT_SIGN_OFF = re.compile(
    rf"(?:单凭|只凭|单看|只看)?(?:这份|这张|这个|这次|该|上述)\s*"
    rf"(?:回显|读回|输出|日志|记录|图例|原图|表格?|截图|抓包)(?:中|里)?"
    rf"(?:就|也|还)?{_CAN}(?:直接|单独)?(?:给|为)\s*{_CHECK_TARGET}(?:做|进行)?(?:验收|下结论)"
    rf"[吗呢]?(?=[。？！?!；;]|$)"
)
_SIGN_OFF_RESULT = re.compile(
    rf"(?:只凭|仅凭|单凭|凭|只看|拿)(?:目前|这|这一|当前|刚才|现在)?[^，,。；;？！?！]{{2,35}}?\s*"
    rf"(?:到底|已经|就|还)?{_CAN}(?:直接|肯定|放心|确实)?\s*(?:填写|填上|填报|写上|写明|判为|算作)\s*"
    rf"{_TARGET}(?:这项|这一项|这一栏)?[吗呢]?(?=[。？！?!；;]|$)"
)
_REQUEST = (
    re.compile(rf"(?:{_CAN}|是否足以)(?:单独|据此|直接)?{_PROOF}{_TARGET}"),
    re.compile(rf"(?:能否|能不能|能|可以|是否能)(?:当作?|作为|算作){_TARGET}的(?:直接)?(?:证明|证据)"),
    re.compile(rf"(?:还缺什么|还(?:需|要|得)(?:看|查|补|核对)什么)(?:证据|材料|记录)?(?:才(?:能|可以))?{_PROOF}{_TARGET}"),
    re.compile(rf"{_CAN}(?:直接|就)?(?:给|在|把|对)\s*{_CHECK_TARGET}{_CHECK_ITEM}?(?:上)?\s*{_SIGN_OFF}"),
    re.compile(rf"{_CAN}(?:直接|就)?(?:写上|写成|填成|填为|标作|标为|记作|记为)\s*{_TARGET}"),
    re.compile(rf"{_CHECK_TARGET}{_CHECK_ITEM}\s*(?:凭[^，。；]{{2,18}})?{_CAN}(?:直接|就)?{_SIGN_OFF}"),
    _ARTIFACT_MEASUREMENT,
    _ARTIFACT_SIGN_OFF,
    _SIGN_OFF_RESULT,
)
_QUESTION_END = re.compile(r"(?:(?:这一项|这项|这一栏))?[吗呢吧呀]+$")
_NON_ASSERTED = re.compile(r"预期|预计|假设|如果|假如|建议|理论上|练习|下一页")
_HYPOTHETICAL = re.compile(r"假设|如果|假如|建议|理论上|练习|下一页")
_LIMIT = re.compile(rf"(?:(?:不足以|不能|无法)(?:(?:单凭|仅凭|只看)[^，。；\n]{{1,24}}?(?:就|便))?"
                    rf"(?:单凭|仅凭|直接|单独|据此|由此)?{_PROOF}|不代表|不能等同于)")
_REQUIRED = re.compile(r"(?:仍|还|另|另外)?(?:需要|需|应|要|得)(?:另外|另|单独|实际|通过|按|结合|同时|分别){1,3}")
_NECESSARY_EVIDENCE = re.compile(r"(?:仍需|还要|需要|应查|必须|需|须)[^。；;\n]{2,100}?"
                                 r"(?:回显|探测|记录|日志|抓包|采样|测量|统计|计时|输出)"
                                 r"[^。；;\n]{0,12}?(?:才(?:能|可)|方(?:能|可)|以)?"
                                 r"(?:证明|证实|确认|判定|判断|验收|量出|验证)")
_INDEPENDENT_MEASUREMENT = re.compile(r"(?:仍|还|另)?(?:然)?(?:需要|需|要|必须)\s*"
                                      r"(?:独立|另行|另|单独|额外)(?:做|作|进行)?"
                                      r"(?:端到端|实际|单独)?(?:计时|测量|探测|采样)")
_MEASUREMENT = re.compile(r"探测|采集|测量|统计|验证|审查|核对|检查|记录")
_MODIFIERS = re.compile(r"已经|已(?=建立|确认|完成|收敛|恢复|成功)|实际|彻底|完全|真的|一定|是否")
_OUTCOME_ENDING = re.compile(r"(?:已(?:经)?|是否)?(?:建立|确认|完成|收敛|恢复|成功)$")
_MEASUREMENT_TAIL = re.compile(r"的?(?:计时|耗时|持续时间|恢复时间|中断时长|用时|秒数|时长)$")
_EVENT_OUTCOME = re.compile(r"[^\W\d_]{2,}(?:恢复|中断|切换|收敛|超时|断流)$")
_SEPARATE_EVIDENCE = re.compile(r"(?P<subject>[^，,。；;\n]{3,30}?)(?:状态|结论|情况)?(?:独立|单独|另外|另行)"
                                r"(?:见|查看|查阅)(?:下一页|上一页|另(?:一)?表|另一(?:次|份)(?:回显|输出))")
_GENERIC = {"状态", "结果", "设备", "这些", "证明", "说明", "结论", "它们", "正常", "通过"}
_ROLE_ALIASES = (("发送侧", "发送端"), ("接收侧", "接收端"), ("发起侧", "发起端"), ("响应侧", "响应端"))
_EXHIBIT_FOCUS = re.compile(r"(?:回显|读回|表项|图示|原表|报文|观察|记录)(?:中|里|了|只能|不表示|的|仍|能|能否|足以|足够)?")


def evidence_limit_target(text: str) -> str:
    for form in _REQUEST:
        if match := form.search(text):
            target = compact_text(_QUESTION_END.sub("", match["target"].strip()).strip('“”‘’「」『』`"'))
            if len(target) >= 3 and target not in _GENERIC:
                return target
    return ""


def evidence_limit_targets(text: str) -> tuple[str, ...]:
    # Keep two quoted verdicts separate even when their combined text exceeds
    # the usual single-target limit or they use a coordinating conjunction.
    clauses = re.split(r"[。；;！？!?\n]", text)
    for clause in clauses:
        if not _JOINT_CHECK.search(clause):
            continue
        quoted = [next(value for value in match.groups() if value is not None)
                  for match in _QUOTED_CLAIM.finditer(clause)]
        items = tuple(compact_text(part) for value in quoted for part in value.split('、'))
        if 2 <= len(items) <= 3 and all(3 <= len(part) <= 52 for part in items):
            return items
    target = evidence_limit_target(text)
    if not target:
        return ()
    if _JOINT_CHECK.search(text):
        items = tuple(part.strip('“”‘’「」『』`"') for part in target.split('、'))
        if 2 <= len(items) <= 3 and all(len(part) >= 3 for part in items):
            return items
    return (target,)


def _comparison(text: str) -> str:
    return compact_text(_MODIFIERS.sub("", text))


def _measurement_terms(text: str) -> set[str]:
    # The same measurement can verify either polarity of an outcome.
    text = re.sub(r"无法|无|没有发生|没有|未发生|未", "", _comparison(text))
    return {text[index:index + 2] for index in range(len(text) - 1)} - _GENERIC


def _evidence_context_matches(target: str, own_claim: str, required: str) -> bool:
    """An explicit requirement may use 'the result' after naming the claim."""
    target = _comparison(target)
    context = _comparison(own_claim)
    condition = _comparison(required)
    for alias, role in _ROLE_ALIASES:
        target, context, condition = (value.replace(alias, role) for value in (target, context, condition))
    if target in context or target in condition:
        return True
    informative = _measurement_terms(target) & _measurement_terms(context)
    if len(informative) >= 2:
        return True
    # A body sentence may name the event while the requirement names its
    # observation side. Retain both as the attribution of one condition.
    return bool(informative and _measurement_terms(target) & _measurement_terms(condition)
                and re.search(r"发送端|接收端|发起端|响应端", target)
                and _EXHIBIT_FOCUS.search(condition))


def evidence_limit_witnesses(target: str, text: str) -> tuple[str, ...]:
    """Return only limitations expressly stated by the evidence itself."""
    if not target:
        return ()
    terms = _measurement_terms(target)
    subject = _OUTCOME_ENDING.sub("", compact_text(target))
    measurement = _MEASUREMENT_TAIL.sub("", _comparison(target))
    witnesses = set()
    for clause in re.split(r"[。；;\n]", text):
        if len(subject) >= 5 and any(subject in compact_text(match["subject"])
                                     and not _NON_ASSERTED.search(clause[:match.end("subject")])
                                     for match in _SEPARATE_EVIDENCE.finditer(clause)):
            witnesses.add("separate_observation")
        if (not _HYPOTHETICAL.search(clause) and (prerequisite := _NECESSARY_EVIDENCE.search(clause))
                and _evidence_context_matches(target, clause[:prerequisite.start()], clause[prerequisite.start():])):
            witnesses.add("required_observation")
        if _NON_ASSERTED.search(clause):
            continue
        if (measurement != _comparison(target) and (condition := _INDEPENDENT_MEASUREMENT.search(clause))
                and (outcome := _EVENT_OUTCOME.search(_comparison(clause[:condition.start()])))
                and outcome[0] in measurement):
            witnesses.add("required_observation")
        if (limit := _LIMIT.search(clause)) and _comparison(target) in _comparison(clause[limit.end():]):
            witnesses.add("excluded_inference")
        if (needed := _REQUIRED.search(clause)) and _MEASUREMENT.search(clause[needed.end():]):
            if len(terms & _measurement_terms(clause)) >= 2:
                witnesses.add("required_observation")
    return tuple(sorted(witnesses))
