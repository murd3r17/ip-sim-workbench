"""BF4-04：15 动作目录与实际路由/方法/副作用/参数一致性的静态对照。

不做真实写设备；验证目录不会指向不存在的 handler，也不再把本地证据写入、
真实 schema 参数和对象归属写错。
"""
from main import app
from modules.trust.service import ACTION_CATALOG

OWNERSHIP = {"any_authenticated", "owner_or_admin", "admin", "admin_cross_owner"}


def test_action_catalog_paths_and_methods_exist():
    import re
    paths = app.openapi()["paths"]

    def norm(value: str) -> str:
        return re.sub(r"\{[^}]+\}", "{}", value).rstrip("/")

    actual = {(norm(template), method.lower()) for template, methods in paths.items() for method in methods}
    missing = []
    for action in ACTION_CATALOG:
        if (norm(action["path"]), action["method"].lower()) not in actual:
            missing.append((action["action_id"], action["method"], action["path"]))
    assert ACTION_CATALOG and not missing


def test_action_catalog_has_roles_cost_side_effect():
    by_id = {item["action_id"]: item for item in ACTION_CATALOG}
    for action in ACTION_CATALOG:
        assert action.get("roles"), action["action_id"]
        assert action.get("cost"), action["action_id"]
        assert action.get("side_effects"), action["action_id"]
        assert action.get("ownership") in OWNERSHIP, action["action_id"]
        assert action.get("device_effect") in {"read_only", "write", "none"}, action["action_id"]

    # 观察动作：设备只读与本地证据写入必须分开表达
    for action_id in ("observe_interfaces", "observe_ospf_peer", "observe_ospf_route"):
        item = by_id[action_id]
        assert item["device_effect"] == "read_only", item
        assert item["side_effects"] == "writes_local_evidence", item
        assert item["cost"] == "device_read", item

    # 预览接口的真实 schema 只有 config_content/device_model，不能列 device_id
    preview = by_id["deploy_preview"]
    assert preview["params"] == ["config_content", "device_model"], preview

    # 本人确认与管理员跨归属审批必须能区分
    assert by_id["deploy_confirm"]["ownership"] == "owner_or_admin"
    assert by_id["deploy_execute"]["ownership"] == "owner_or_admin"
    assert by_id["approval_confirm"]["ownership"] == "admin_cross_owner"
    assert by_id["approval_confirm"]["roles"] == ["admin"]
    for action_id in ("preflight_environment", "update_environment", "update_config"):
        assert by_id[action_id]["ownership"] == "admin", by_id[action_id]
