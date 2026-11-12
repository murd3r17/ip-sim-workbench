"""LLMService单元测试"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_provider(response: str = None):
    """创建带name属性的mock provider"""
    provider = AsyncMock()
    provider.__class__.__name__ = "MockProvider"
    provider.name = "MockProvider"
    if response is not None:
        provider.generate.return_value = response
    return provider


class TestLLMServiceGenerateCLI:
    """测试 generate_cli_commands"""

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_cli_basic(self, mock_factory, mock_db):
        """基本CLI生成测试"""
        provider = _make_mock_provider(json.dumps({
            "commands": ["sysname CoreRouter01"],
            "explanation": "修改主机名",
            "warnings": [],
        }))
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_cli_commands("把设备主机名改为CoreRouter01")

        assert "commands" in result
        assert "sysname CoreRouter01" in result["commands"]
        assert result["explanation"] == "修改主机名"

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_cli_safety_filter(self, mock_factory, mock_db):
        """安全过滤测试：拦截危险命令"""
        provider = _make_mock_provider(json.dumps({
            "commands": ["sysname TestDevice", "format flash:"],
            "explanation": "测试",
            "warnings": [],
        }))
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_cli_commands("格式化flash")

        # format flash应被拦截
        assert "format flash:" not in result["commands"]
        assert "_raw_commands" not in result
        assert "raw_commands" not in result
        assert any("拦截" in w for w in result["warnings"])

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_cli_json_parse_error(self, mock_factory, mock_db):
        """LLM返回非法JSON时的降级处理"""
        provider = _make_mock_provider("这不是JSON格式的回复")
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_cli_commands("测试")

        assert result["commands"] == []
        assert "格式异常" in result["warnings"][0]

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_cli_accepts_json_array_after_thinking_response(self, mock_factory, mock_db):
        """思考文本后的数组式重试结果应转换为可展示的命令结果"""
        provider = _make_mock_provider()
        provider.generate.side_effect = [
            "Thinking Process:\n模型未在首次响应中给出最终JSON。",
            json.dumps(["isis 1", "network-entity 49.0001.0000.0000.0001.00"]),
        ]
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_cli_commands("为路由器接口配置ISIS")

        assert result["commands"] == ["isis 1", "network-entity 49.0001.0000.0000.0001.00"]
        assert result["explanation"] == "命令已生成"


class TestLLMServiceGenerateAndValidate:
    """测试 generate_and_validate 闭环"""

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_and_validate_basic(self, mock_factory, mock_db):
        """基本闭环测试：生成+校验"""
        provider = _make_mock_provider(json.dumps({
            "commands": ["sysname CoreRouter01"],
            "explanation": "修改主机名",
            "warnings": [],
        }))
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_and_validate("把设备主机名改为CoreRouter01", "NE40E")

        assert "commands" in result
        assert "validation_results" in result
        assert "all_passed" in result
        assert "high_risk_commands" in result
        assert result["all_passed"] is True

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_and_validate_with_warnings(self, mock_factory, mock_db):
        """校验失败场景：命令参数不合法"""
        provider = _make_mock_provider(json.dumps({
            "commands": ["ip address not-an-ip"],
            "explanation": "测试",
            "warnings": [],
        }))
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_and_validate("配置IP地址", "NE40E")

        # L1校验会失败（ip address需要在interface视图下）
        assert result["all_passed"] is False

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_and_validate_high_risk_blocked(self, mock_factory, mock_db):
        """高危命令拦截测试"""
        provider = _make_mock_provider(json.dumps({
            "commands": ["reset saved-configuration"],
            "explanation": "重置配置",
            "warnings": [],
        }))
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_and_validate("重置配置", "NE40E")

        # 高危命令应被检测
        assert len(result["high_risk_commands"]) > 0
        assert result["all_passed"] is False


class TestLLMServiceStructuredAI:
    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_config_plan_reports_model_connection_failure(self, mock_factory, mock_db):
        from core.llm_provider import LLMUnavailableError
        provider = _make_mock_provider("")
        provider.generate.side_effect = LLMUnavailableError("当前AI服务不可用，请稍后重试。")
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        with pytest.raises(LLMUnavailableError):
            await LLMService(db=mock_db, user_id=1).generate_config_plan(
                "生成配置", [{"device_id": 1, "hostname": "A-BRAS"}]
            )

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_config_plan_accepts_six_device_names_from_markdown_json(self, mock_factory, mock_db):
        devices = [
            {"device_id": 1, "hostname": "A-BRAS"},
            {"device_id": 2, "hostname": "A_MB_1"},
            {"device_id": 3, "hostname": "A_MB_2"},
            {"device_id": 4, "hostname": "A-PE-1"},
            {"device_id": 5, "hostname": "A-PE-2"},
            {"device_id": 6, "hostname": "A-RR"},
        ]
        response = """以下是脚本：
```json
{"items": [
  {"device": "A-BRAS", "config_content": "interface GigabitEthernet3/0/8"},
  {"device": "A_MB_1", "config_content": "ip ip-prefix BRAS index 10 permit 10.1.1.0 30"},
  {"device_name": "A_MB_2", "config_content": "route-policy BRAS permit node 10"},
  {"hostname": "A-PE-1", "config_content": "bgp 65000"},
  {"device": "A-PE-2", "config_content": "bgp 65000"},
  {"device": "A-RR", "config_content": "bgp 65000"}
]}
```
"""
        mock_factory.return_value = _make_mock_provider(response)

        from modules.ai_text.llm_service import LLMService
        result = await LLMService(db=mock_db, user_id=1).generate_config_plan("生成多设备脚本", devices)

        assert [item["device_id"] for item in result["items"]] == [1, 2, 3, 4, 5, 6]

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_config_plan_accepts_six_markdown_device_script_sections(self, mock_factory, mock_db):
        devices = [
            {"device_id": 1, "hostname": "A-BRAS"}, {"device_id": 2, "hostname": "A_MB_1"},
            {"device_id": 3, "hostname": "A_MB_2"}, {"device_id": 4, "hostname": "A-PE-1"},
            {"device_id": 5, "hostname": "A-PE-2"}, {"device_id": 6, "hostname": "A-RR"},
        ]
        response = """### A-BRAS 配置
interface GigabitEthernet3/0/8
 ip address 10.1.1.1 255.255.255.252
### A_MB_1 配置
ip ip-prefix BRAS index 10 permit 10.1.1.0 30
### A_MB_2 配置
route-policy BRAS permit node 10
### A-PE-1 配置
bgp 65000
### A-PE-2 配置
bgp 65000
### A-RR 配置
bgp 65000
"""
        mock_factory.return_value = _make_mock_provider(response)

        from modules.ai_text.llm_service import LLMService
        result = await LLMService(db=mock_db, user_id=1).generate_config_plan("生成多设备脚本", devices)

        assert [item["device_id"] for item in result["items"]] == [1, 2, 3, 4, 5, 6]
        assert result["items"][0]["config_content"].startswith("interface GigabitEthernet3/0/8")

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_config_plan_keeps_per_device_scripts(self, mock_factory, mock_db):
        provider = _make_mock_provider(json.dumps({
            "assumptions": ["接口已存在"], "warnings": [], "order": [1, 2],
            "items": [{"device_id": 1, "config_content": "isis 1"}, {"device_id": 2, "config_content": "isis 2"}],
        }))
        mock_factory.return_value = provider
        from modules.ai_text.llm_service import LLMService
        result = await LLMService(db=mock_db, user_id=1).generate_config_plan("配置ISIS", [{"device_id": 1, "hostname": "R1"}, {"device_id": 2, "hostname": "R2"}])
        assert result["items"] == [{"device_id": 1, "config_content": "isis 1"}, {"device_id": 2, "config_content": "isis 2"}]

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_generate_report(self, mock_factory, mock_db):
        provider = _make_mock_provider(json.dumps({
            "title": "巡检报告",
            "summary": "总体正常",
            "key_findings": ["无告警"],
            "root_causes": ["无"],
            "impact_analysis": ["无影响"],
            "recommendations": ["保持观察"],
            "report_text": "完整报告",
        }))
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.generate_report("巡检报告", "日志内容")

        assert result["title"] == "巡检报告"
        assert result["report_text"] == "完整报告"
        assert result["key_findings"] == ["无告警"]

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_coach_training(self, mock_factory, mock_db):
        provider = _make_mock_provider(json.dumps({
            "goal": "完成接口配置",
            "summary": "先进入接口视图",
            "next_steps": ["进入接口视图", "配置IP地址"],
            "corrections": ["命令必须在接口视图下执行"],
            "explanations": ["接口地址属于三层接口配置"],
            "risk_notes": ["避免误在系统视图下执行"],
            "coach_text": "完整教练建议",
        }))
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.coach_training("完成接口配置", "当前在系统视图", "display current-configuration")

        assert result["goal"] == "完成接口配置"
        assert result["coach_text"] == "完整教练建议"
        assert result["next_steps"] == ["进入接口视图", "配置IP地址"]


class TestLLMServiceLogs:
    """测试日志查询和反馈"""

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_set_feedback(self, mock_factory, mock_db):
        """设置反馈测试"""
        provider = _make_mock_provider()
        mock_factory.return_value = provider

        # 模拟数据库查询返回
        mock_log = MagicMock()
        mock_log.feedback = None
        mock_log.user_id = 1
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_log
        mock_db.execute.return_value = mock_result

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        success = await service.set_feedback(1, "good")

        assert success is True
        assert mock_log.feedback == "good"

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_set_feedback_not_found(self, mock_factory, mock_db):
        """设置反馈 - 日志不存在"""
        provider = _make_mock_provider()
        mock_factory.return_value = provider

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        success = await service.set_feedback(999, "bad")

        assert success is False

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_set_feedback_wrong_owner(self, mock_factory, mock_db):
        """设置反馈 - 非日志所有者"""
        provider = _make_mock_provider()
        mock_factory.return_value = provider

        mock_log = MagicMock()
        mock_log.feedback = None
        mock_log.user_id = 999  # different user
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_log
        mock_db.execute.return_value = mock_result

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        success = await service.set_feedback(1, "bad")

        assert success is False

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_set_feedback_invalid_value(self, mock_factory, mock_db):
        """设置反馈 - 无效值"""
        provider = _make_mock_provider()
        mock_factory.return_value = provider

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)

        with pytest.raises(ValueError, match="feedback must be"):
            await service.set_feedback(1, "invalid")

    @pytest.mark.asyncio
    @patch("modules.ai_text.llm_service.create_llm_provider")
    async def test_get_logs(self, mock_factory, mock_db):
        """查询日志测试"""
        provider = _make_mock_provider()
        mock_factory.return_value = provider

        # 模拟count查询
        count_result = MagicMock()
        count_result.scalar.return_value = 5
        # 模拟items查询
        items_result = MagicMock()
        items_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [count_result, items_result]

        from modules.ai_text.llm_service import LLMService
        service = LLMService(db=mock_db, user_id=1)
        result = await service.get_logs(page=1, page_size=20)

        assert "items" in result
        assert "total" in result
        assert result["total"] == 5


class TestModuleImports:
    """测试所有模块可正常import"""

    def test_import_llm_provider(self):
        from core.llm_provider import LLMProvider, OllamaProvider, OpenAICompatibleProvider, FallbackProvider, create_llm_provider
        assert LLMProvider is not None

    def test_import_llm_service(self):
        from modules.ai_text.llm_service import LLMService
        assert LLMService is not None

    def test_import_models(self):
        from modules.ai_text.models import AILog
        assert AILog.__tablename__ == "ai_log"

    def test_import_schemas(self):
        from modules.ai_text.schemas import (
            CLIRequest, CLIResponse, ReviewRequest, ReviewResponse,
            GenerateValidateRequest, GenerateValidateResponse,
            ReportRequest, ReportResponse, CoachRequest, CoachResponse,
            FeedbackRequest, AILogResponse, AILogListResponse,
        )
        assert GenerateValidateRequest is not None
        assert GenerateValidateResponse is not None

    def test_import_router(self):
        from modules.ai_text.router import router
        assert router.prefix == "/ai"

    def test_import_vrp_validator(self):
        from modules.deploy.vrp_validator import VRPValidator
        assert VRPValidator is not None

    def test_import_eval_script(self):
        from scripts.ai_accuracy_eval import SCENARIOS, DEVICE_MODELS, run_static_eval
        assert len(SCENARIOS) == 20
        assert len(DEVICE_MODELS) == 3
