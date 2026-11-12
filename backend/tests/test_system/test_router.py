"""系统管理模块路由测试"""
import pytest
from modules.system.router import router


class TestSystemRouter:
    def test_router_exists(self):
        assert router is not None

    def test_router_prefix(self):
        assert router.prefix == "/system"

    def test_router_has_routes(self):
        assert len(router.routes) > 0

    def test_router_tags(self):
        assert "系统管理" in router.tags

    def test_route_paths(self):
        paths = [route.path for route in router.routes]
        assert "/system/info" in paths
        assert "/system/config" in paths
        assert "/system/audit-logs" in paths
        assert "/system/tasks" in paths
        assert "/system/logs" in paths
        assert "/system/health" in paths
