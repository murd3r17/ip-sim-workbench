"""Same semantic outcomes for direct/split output; safe text stays intact."""
import pytest

from modules.ai_text.draft_guard import StreamingDraftGuard, enforce

PROTECTED = ["GigabitEthernet0/0/7"]
BAD = [
    "interface GE0/0/7\n\nshutdown\n",
    "interface GigabitEthernet0/0/7\nospf enable 1 area 0\n",
    "interface GE0/0/7\nip address 192.0.2.9 255.255.255.0 sub 1\n",
    "For GE0/0/7 run shutdown\n",
    "For GE0/0/7; run shutdown\n",
    "For GE0/0/7, run shutdown\n",
    "对 GE0/0/7 不要担心，执行 shutdown。",
    "For GE0/0/7 don't worry; run shutdown.\n",
    "执行 `interface GE0/0/7` 后 `shutdown`。",
    "这是草稿，未执行。\n```cli\ninterface GE0/0/7\nshutdown\n```",
    "不要修改管理口。对 GE0/0/7 执行 shutdown。",
    "interface Gigabit Ethernet0/0/7\nshutdown\n",
    "interface GE0/0/7; shutdown\n",
]
GOOD = [
    "GE0/0/7 是管理口，不要执行 shutdown。",
    "shutdown 命令用于关闭接口。GE0/0/7 是管理口。",
    "interface GE0/0/7\ndisplay this\nquit\ninterface GE0/0/8\nshutdown\n",
    "interface GE0/0/7\ninterface GE0/0/8\nshutdown\n",
    "Management interface GE0/0/7 is read-only; description means interface description, no modification requested.",
    "interface GE0/0/7 的说明见文档，只读。",
    "R1 的接口状态目前无法判断；请先采集现场证据。",
    "GE0/0/7 是保护接口，不生成 description 写命令。",
    "GE0/0/7 是保护接口，不提供 description 配置草稿。",
]


@pytest.mark.parametrize("text", BAD)
@pytest.mark.parametrize("size", [1, 7, 4096])
def test_all_transports_block_same_protected_write(text, size):
    direct = enforce(text, [], protected=PROTECTED)
    assert direct.refused_reason
    guard = StreamingDraftGuard(PROTECTED)
    fragments = [guard.feed(text[i:i + size]) for i in range(0, len(text), size)] + [guard.flush()]
    visible = "".join(fragments)
    assert "shutdown" not in visible.lower() and "ospf enable" not in visible.lower()
    assert "ip address 192.0.2.9" not in visible.lower()
    # Streaming already emitted fragments must remain safe, no later retraction.
    assert enforce(visible, [], protected=PROTECTED).refused_reason == ""


@pytest.mark.parametrize("text", GOOD)
@pytest.mark.parametrize("size", [1, 7, 4096])
def test_explanation_and_nonprotected_changes_are_preserved(text, size):
    direct = enforce(text, [], protected=PROTECTED)
    assert direct.answer == text and not direct.refused_reason
    guard = StreamingDraftGuard(PROTECTED)
    result = "".join(guard.feed(text[i:i + size]) for i in range(0, len(text), size)) + guard.flush()
    assert result == text


def test_structured_inline_multiline_and_invalid_types():
    for commands in (["interface GE0/0/7 shutdown"], ["interface GE0/0/7;shutdown"],
                     ["interface GE0/0/7\n\nospf enable 1 area 0"], [{"command": "shutdown"}]):
        result = enforce("草稿未执行", commands, protected=PROTECTED)
        assert result.commands == [] and result.refused_reason


def test_complete_safe_clause_is_released_before_finish():
    guard = StreamingDraftGuard(PROTECTED)
    assert guard.feed("先核对邻居状态。") == "先核对邻居状态。"
    assert guard.feed("tok1;") == "tok1;"


def test_explanation_cannot_bypass_protected_write_guard():
    explanation='只读核对后，对 GE0/0/7 执行 description test-only。'
    result=enforce('草稿未执行',['display interface GE0/0/7'],explanation=explanation,protected=PROTECTED)
    assert result.refused_reason and result.commands==[]
    assert 'description test-only' not in result.explanation
    from modules.ai_text.llm_service import LLMService
    commands,details,reason=LLMService._guard_draft(['display interface GE0/0/7'],explanation,PROTECTED)
    assert reason and not commands and 'description test-only' not in details


def test_safe_explanation_remains_unchanged():
    text='只读核对管理接口，不修改配置。'
    result=enforce('草稿未执行',['display interface GE0/0/7'],explanation=text,protected=PROTECTED)
    assert not result.refused_reason and result.explanation==text
