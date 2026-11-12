"""实训教练提示词回归（2026-10-05 用户实测反馈后的加固）。

背景：用户做 OSPF 实训时，AI 教练只给泛泛思路，必须追问「我到底要干什么」才给细节；
并且它不知道「配置下发」的 5 步流程（把 confirmed 当成已下发）。这组用例锁定：
1. 助手系统提示必须带「工作台操作手册」（真实模块名/按钮/状态语义）；
2. 教练输出规范必须要求"模块→按钮→命令→看什么→通过标准→下一步"的结构；
3. coach_training 的 prompt 必须带上手册 + 规范 + 结构化输出契约；
4. 工作台手册里必须写明 confirmed 只是确认、还没下发（避免再次误答）。
"""

import json

import pytest

from modules.ai_text.llm_service import LLMService


class _CaptureProvider:
    """记录 prompt 的假 provider。"""

    name = "capture"

    def __init__(self, payload: dict | None = None):
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.payload = payload or {
            "summary": "第 1 步：核对互联地址",
            "next_steps": ["左侧「WebSSH终端」→ 选 R1 → 点「连接」→ 输入 display ip interface brief → 看 GE3/0/3 是否 up"],
            "corrections": [],
            "explanations": [],
            "risk_notes": [],
            "coach_text": "第一步照这个做……",
        }

    async def generate(self, prompt, system=None, max_tokens=None, temperature=None):
        self.prompts.append(prompt)
        self.systems.append(system or "")
        return json.dumps(self.payload, ensure_ascii=False)

    async def health_check(self):
        return True


class TestCopilotSystemPrompt:
    def test_includes_workbench_guide(self):
        prompt = LLMService.copilot_system_prompt()

        assert "工作台操作手册" in prompt
        # 真实模块名（回答"去哪里做"时必须引用这些）
        for module in ("终端", "配置下发", "变更审批", "配置版本", "实训", "告警"):
            assert module in prompt, f"手册缺少模块：{module}"

    def test_deploy_flow_and_status_semantics_are_spelled_out(self):
        prompt = LLMService.copilot_system_prompt()

        assert "配置下发（5 步" in prompt
        for step in ("创建任务", "确认", "执行", "验证报告", "查看结果"):
            assert step in prompt, f"5 步流程缺少：{step}"
        # 实测踩过的坑：confirmed 被当成"已下发到设备"
        assert "confirmed=已确认未执行" in prompt
        assert "这只是确认，配置还没下发到设备" in prompt

    def test_webssh_occupancy_and_paste_are_documented(self):
        prompt = LLMService.copilot_system_prompt()

        assert "同一设备同一时刻只允许一个操作方" in prompt
        assert "设备终端占用中" in prompt
        assert "Ctrl+V" in prompt

    def test_guide_can_be_omitted(self):
        # 注意：角色规则里会提到"下方【工作台操作手册】"，所以用手册正文的标记判断
        without_guide = LLMService.copilot_system_prompt(with_guide=False)
        assert "【工作台操作手册（回答" not in without_guide
        assert "配置下发（5 步" not in without_guide
        assert "【工作台操作手册（回答" in LLMService.copilot_system_prompt()


class TestTrainingCoachRules:
    def test_rules_require_concrete_output_structure(self):
        rules = LLMService.TRAINING_COACH_RULES

        for section in ("去哪做", "具体操作", "看什么", "通过标准", "做完回我", "下一步预告"):
            assert section in rules, f"输出规范缺少环节：{section}"

    def test_rules_tell_coach_to_be_concrete_on_step_questions(self):
        rules = LLMService.TRAINING_COACH_RULES

        assert "要完整可执行的指令" in rules
        assert "不要只给原则" in rules or "不是思路综述" in rules

    def test_rules_cover_terminal_occupancy(self):
        rules = LLMService.TRAINING_COACH_RULES

        assert "占着某台设备时，你无法代跑命令" in rules
        assert "不要因为无法核验就不给指令" in rules
        assert "don't" not in rules.lower()  # 中文规范，避免混入英文模板残留


class TestCoachTrainingPrompt:
    @pytest.mark.asyncio
    async def test_prompt_carries_guide_rules_and_contract(self):
        provider = _CaptureProvider()
        service = LLMService(provider=provider)

        result = await service.coach_training(
            goal="OSPF 单区域基础实验完整版",
            scenario="实验步骤清单（共 4 步）:\n步骤1: 互联与环回地址核对 | 目标: 核对地址 | 验证: display ip interface brief 期望出现 up",
            current_step=None,
            history=None,
        )

        assert result["goal"] == "OSPF 单区域基础实验完整版"
        assert provider.prompts, "应当调用模型"
        prompt = provider.prompts[0]

        assert "工作台操作手册" in prompt
        assert "实训教练输出规范" in prompt
        assert "next_steps" in prompt and "可直接照做的动作" in prompt
        # 明确要求把「配置下发」当前该点哪个按钮写出来
        assert "创建任务 / 确认下发 / 执行 / 验证" in prompt

    @pytest.mark.asyncio
    async def test_degraded_response_still_returns_contract_fields(self):
        class _BrokenProvider:
            name = "broken"

            async def generate(self, prompt, system=None, max_tokens=None, temperature=None):
                return "这不是 JSON"

            async def health_check(self):
                return False

        service = LLMService(provider=_BrokenProvider())
        result = await service.coach_training(goal="实验A", scenario="场景", current_step=None, history=None)

        for field in ("goal", "summary", "next_steps", "corrections", "explanations", "risk_notes", "coach_text"):
            assert field in result
