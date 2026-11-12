from modules.ai_text.draft_guard import enforce

def test_interface_name_with_space_is_protected():
    r = enforce("", ["interface GigabitEthernet 0/0/0", "shutdown"])
    assert r.commands == []
    assert r.refused_reason

def test_interface_alias_ge_is_protected():
    r = enforce("", ["interface GE0/0/0", "undo ip address"])
    assert r.commands == []
    assert r.refused_reason
