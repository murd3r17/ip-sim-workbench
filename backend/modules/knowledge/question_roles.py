"""Identify the kind of textbook evidence requested in a natural question."""

from dataclasses import dataclass
import re


_ASK = re.compile(r"哪(?:里|[一几]?[边端侧个项条位类种段层])|谁|多少|几(?:份|次|条|个|位|项)|什么|"
                  r"有无|有没有|是否|有何|为什么|为何|如何|怎么|怎样")
_EPISODE = re.compile(r"当时|那轮|那次|这一轮|这一次|这回|当次|做完以后|完成后|结束之后|操作完|起初|此次观察")
_DEMONSTRATIVE = re.compile(r"(?:书|教材|课件|讲义)(?:里|上|中)|这(?:张|幅|页|里的)|那(?:张|幅|页|条)|"
                           r"(?:同一|那次)(?:个|份)?(?:例子|图|表)")
_MEASURED = re.compile(r"(?:已经|实际|当时|最后|随后|最先|先后)(?:拿到|见到|读到|收到|测到|留下|出现)|"
                       r"(?:拿到|收到|送出|发出|测到|记录|排出|弹出|剩下|留下|回了|掉到)(?:了|的)|"
                       r"数字|结果|读数|条目|所见|哪(?:项|条)有效")
_VISUAL_LABEL = re.compile(r"线型|颜色|图例|标记|小字|箭头|圆点|方框|圆框|色块|连线")
_MECHANISM = re.compile(r"(?:谁|哪(?:一)?(?:端|边|方|侧))\s*(?:先|最先|首先|随后|负责|是)?\s*(?:发|收|回|处理|建立|查|送|触发)|"
                        r"为什么|为何|起什么作用|有什么用途|怎么(?:配合|工作|传递|选择|处理)|依赖什么|由谁")
_COMMAND = re.compile(r"(?:用的|核对用的|配置时用的)(?:这条|那条|哪个)?[^，。？]{0,12}(?:命令|设置)\s*(?:是)?(?:什么|哪)|"
                      r"(?:哪一条|哪条|什么)(?:只读|配置|查看|核对)?命令")
_EXTERNAL_ACTION = re.compile(r"(?:请|现在|直接|现场|顺手)(?:去|立即)?(?:登录|接入|连接|实际操作|执行命令|连设备)|"
                              r"^(?:请)?(?:画|绘制|生成|制作)(?:一)?(?:张|个)?.{0,20}(?:示意图|流程图|图表)")
_VISUAL_MARK = re.compile(r"(?:(?P<color>[红黄蓝绿黑白灰紫橙])(?:色)?(?:的)?\s*)?"
                          r"(?P<shape>虚线|实线|连线|线条|线|箭头|色块|方框|圆框|圆点)")
_VISUAL_ASSERTION = re.compile(r"表示|标出|标注|代表|连接|连起来|指向|通向|对应|写为|填为")
_CONJECTURE = re.compile(r"预计|预测|假设|如果|计划")
_NEGATIVE_MARK = re.compile(r"不是|不表示|不代表|未标出")


@dataclass(frozen=True)
class QuestionRole:
    kind: str
    axes: frozenset[str] = frozenset()


def _marks(text):
    for match in _VISUAL_MARK.finditer(text):
        color, shape = match["color"], match["shape"]
        if color or shape != "线":
            yield match, color or "", "线" if shape in {"连线", "线条"} else shape


def visual_marks(text):
    return frozenset((color, shape) for _, color, shape in _marks(text) if color or shape in {"虚线", "实线"})


def has_requested_visual_marks(asked, source):
    """A caption must assert the precise color and line type named in the question."""
    statements = [sentence for sentence in re.split(r"[。；！？\n]", source) if not _NEGATIVE_MARK.search(sentence)]
    for color, shape in asked:
        shapes = {"线", "虚线", "实线"} if shape == "线" else {shape}
        if not any((not color or source_color == color) and source_shape in shapes
                   and _VISUAL_ASSERTION.search(sentence, match.end())
                   for sentence in statements for match, source_color, source_shape in _marks(sentence)):
            return False
    return True


def natural_question_role(text):
    if not _ASK.search(text) or _EXTERNAL_ACTION.search(text):
        return None
    if _COMMAND.search(text):
        return QuestionRole("configuration")
    if _DEMONSTRATIVE.search(text) and (_VISUAL_LABEL.search(text) or visual_marks(text)):
        return QuestionRole("diagram")
    if (_MEASURED.search(text) and (_EPISODE.search(text) or re.search(r"实际|先后|之后|以前|改完|做完", text))
            and (not _CONJECTURE.search(text) or "实际" in text)):
        axes = set()
        if re.search(r"几(?:份|次|条|个|位|项)|多少|数目", text):
            axes.add("count")
        if re.search(r"(?:谁|哪(?:一)?(?:端|边|侧)).{0,12}(?:发|送出)", text):
            axes.add("sender")
        if re.search(r"(?:谁|哪(?:一)?(?:端|边|侧)).{0,12}(?:收|拿到)", text):
            axes.add("receiver")
        if re.search(r"(?:端口|设备|接口)(?:的)?(?:角色|状态)|是什么状态|哪类角色", text):
            axes.add("role" if "角色" in text else "state")
        return QuestionRole("readback", frozenset(axes))
    if _MECHANISM.search(text):
        return QuestionRole("mechanism")
    return None
