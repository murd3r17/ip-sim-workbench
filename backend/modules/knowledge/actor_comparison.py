"""Identify two independent textbook roles from attributable original assertions."""

from dataclasses import dataclass
from itertools import permutations
import re

from .facet_evidence import FacetEvidenceRef


_NAME = r"[A-Za-z][A-Za-z0-9_-]*(?:[ \t]+[A-Za-z][A-Za-z0-9_-]*){0,2}"
_PREMISE = re.compile(rf"(?:我)?(?:原来|以前|最初|原先|原本|原)?以为\s*(?P<a>{_NAME})\s*(?:就是|等同于)\s*(?P<b>{_NAME})\s*[；;。]\s*")
_COMPARISON = re.compile(rf"(?:请)?(?:对比|比较)\s*(?P<a>{_NAME})\s*(?:和|与|vs\.?|/)\s*(?P<b>{_NAME})\s*[；;。:：，,]\s*", re.I)
_TEACHING_SCOPE = re.compile(r"[？?。！!]+\s*(?:不(?:用|必|要)套(?:用)?(?:某个|具体|真实的)?(?:实验|案例)|"
                             r"(?:只|仅)讲(?:教材)?(?:原理|原书内容))[。！!]*\s*$")
_ASK_ACTOR = re.compile(r"^(?:到底|究竟|而|又|再)?\s*(?:由)?(?:谁|哪一端|哪个角色|哪一方)(?P<predicate>[^。；，、？]{1,30})$")
_ACTOR = r"客户端|服务端|服务器|发送端|接收端|发起端|请求端|响应端|查询方|请求方|发送方|接收方|设备端|设备|主机|客户"
_TITLE = re.compile(r"^\*\*([^*]{1,64})\*\*\s*")
_CASE = re.compile(r"本例|该例|本实验|该实验|计划|预期|假设|配置下|图中|截图|日志|命令|(?:请|要)查看")
_CONDITIONAL = re.compile(r"如果|假若|假如|取决于|仅当|(?:未|不)\s*(?:发|查|回应|返回|接收)")
_ROLES = (
    (r"发(?:送|起|出)?", r"(?:发出|发送|发起|发(?=请求|报文|数据|应答))"),
    (r"查(?:询|找)?", r"(?:查询|查找)"),
    (r"接(?:收)?|收(?:到)?", r"(?:接收|收到)"),
    (r"回(?:复|应|包)?|应答", r"(?:应答|响应|回复|返回)"),
)


@dataclass(frozen=True)
class ActorQuestion:
    text: str
    action: str
    target: str


@dataclass(frozen=True)
class ActorComparison:
    topics: tuple[str, str]
    tasks: tuple[ActorQuestion, ActorQuestion]


def actor_comparison_request(query: str) -> ActorComparison | None:
    pair = _PREMISE.match(query) or _COMPARISON.match(query)
    if not pair or pair["a"].casefold() == pair["b"].casefold() or _CASE.search(query):
        return None
    scope = _TEACHING_SCOPE.search(query)
    rest = query[pair.end():scope.start() if scope else None].rstrip("？?。")
    clauses = re.split(r"[，,、；;]", rest)
    if len(clauses) != 2:
        return None
    tasks = []
    for clause in clauses:
        if not (asked := _ASK_ACTOR.fullmatch(clause.strip())):
            return None
        for actor_verb, source_verb in _ROLES:
            if match := re.fullmatch(rf"(?:{actor_verb})(?P<object>[\u3400-\u9fffA-Za-z0-9 _-]{{1,16}})", asked["predicate"]):
                target = match["object"].strip()
                if len(target) >= 2:
                    tasks.append(ActorQuestion(clause.strip(), source_verb, target))
                break
    if len(tasks) != 2 or tasks[0].action == tasks[1].action:
        return None
    return ActorComparison((pair["a"], pair["b"]), (tasks[0], tasks[1]))


def _topic(text: str) -> str:
    return re.sub(r"\s+", "", text.rstrip("。.!:：")).casefold()


def original_actors(paragraph: str, topic: str, task: ActorQuestion, other: str = "") -> frozenset[str]:
    """A matching original title scopes its own direct actor assertion only."""
    title = _TITLE.match(paragraph)
    if not title or _CASE.search(paragraph):
        return frozenset()
    heading, name = _topic(title[1]), _topic(topic)
    if heading != name and not heading.startswith(name + "的"):
        return frozenset()
    foreign = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(other)}(?![A-Za-z0-9_-])", re.I) if other else None
    if foreign and foreign.search(title[1]):
        return frozenset()
    relation = re.compile(rf"(?P<actor>{_ACTOR})\s*(?:(?:用|按)[^。，；]{{0,10}})?{task.action}"
                          rf"\s*[^。，；]{{0,10}}{re.escape(task.target)}")
    return frozenset(match["actor"] for sentence in re.split(r"[。；\n]", paragraph[title.end():])
                     if not _CONDITIONAL.search(sentence) and not (foreign and foreign.search(sentence))
                     for match in relation.finditer(sentence))


def choose_actor_evidence(request: ActorComparison, passages) -> tuple[dict, ...]:
    matches = {}
    for passage in passages:
        if not (reference := FacetEvidenceRef.from_hit(passage)):
            continue
        for number, task in enumerate(request.tasks):
            for index, topic in enumerate(request.topics):
                if actors := original_actors(passage["text"], topic, task, request.topics[1 - index]):
                    matches.setdefault((number, topic), {})[reference] = actors, passage
    solutions = []
    for topics in permutations(request.topics):
        arms = tuple(matches.get((number, topic), {}) for number, topic in enumerate(topics))
        if all(len(choices) == 1 for choices in arms):
            solutions.append(tuple(next(iter(choices.values())) for choices in arms))
    if len(solutions) != 1 or any(len(actors) != 1 for actors, _ in solutions[0]):
        return ()
    return tuple(passage for _, passage in solutions[0])
