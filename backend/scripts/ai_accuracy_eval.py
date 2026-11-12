"""AI配置生成准确率评估脚本

3设备型号 × 20场景 = 60用例
评估维度：命令格式正确率、VRP四层校验通过率、安全过滤率

用法:
    cd backend
    python -m scripts.ai_accuracy_eval [--output report.json]
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict

# 添加backend到path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.deploy.vrp_validator import VRPValidator


DEVICE_MODELS = ["NE40E", "AR6000", "S6700"]

# 20个典型运维场景
SCENARIOS = [
    {
        "id": 1,
        "name": "配置设备主机名",
        "prompt": "把设备主机名改为CoreRouter01",
        "expected_keywords": ["sysname CoreRouter01"],
        "category": "基础配置",
    },
    {
        "id": 2,
        "name": "配置接口IP地址",
        "prompt": "在GigabitEthernet0/0/1接口配置IP地址192.168.1.1，掩码255.255.255.0",
        "expected_keywords": ["interface GigabitEthernet0/0/1", "ip address 192.168.1.1 255.255.255.0"],
        "category": "接口配置",
    },
    {
        "id": 3,
        "name": "创建LoopBack接口",
        "prompt": "创建LoopBack0接口并配置IP地址10.0.0.1/32",
        "expected_keywords": ["interface LoopBack0", "ip address 10.0.0.1"],
        "category": "接口配置",
    },
    {
        "id": 4,
        "name": "配置OSPF单区域",
        "prompt": "配置OSPF进程1，将192.168.1.0/24网段宣告到区域0",
        "expected_keywords": ["ospf 1", "area 0", "192.168.1.0"],
        "category": "路由协议",
    },
    {
        "id": 5,
        "name": "配置OSPF多区域",
        "prompt": "配置OSPF进程1，将10.1.0.0/16加入区域0，10.2.0.0/16加入区域1",
        "expected_keywords": ["ospf 1", "area 0", "area 1"],
        "category": "路由协议",
    },
    {
        "id": 6,
        "name": "配置BGP邻居",
        "prompt": "配置BGP AS 65001，与对端10.0.0.2建立IBGP邻居关系",
        "expected_keywords": ["bgp 65001", "peer 10.0.0.2"],
        "category": "路由协议",
    },
    {
        "id": 7,
        "name": "配置静态路由",
        "prompt": "添加一条默认路由，下一跳为10.0.0.1",
        "expected_keywords": ["ip route-static 0.0.0.0"],
        "category": "路由配置",
    },
    {
        "id": 8,
        "name": "配置VLAN",
        "prompt": "创建VLAN 100，名称为Office",
        "expected_keywords": ["vlan 100"],
        "category": "二层配置",
    },
    {
        "id": 9,
        "name": "配置接口加入VLAN",
        "prompt": "将GigabitEthernet0/0/2接口划入VLAN 100",
        "expected_keywords": ["interface GigabitEthernet0/0/2", "port default vlan 100"],
        "category": "二层配置",
    },
    {
        "id": 10,
        "name": "配置ACL基本规则",
        "prompt": "创建ACL 2000，允许192.168.1.0/24网段访问",
        "expected_keywords": ["acl 2000", "rule permit source 192.168.1.0"],
        "category": "安全配置",
    },
    {
        "id": 11,
        "name": "配置ACL拒绝规则",
        "prompt": "在ACL 2001中添加拒绝所有TCP流量的规则",
        "expected_keywords": ["acl 2001", "rule deny"],
        "category": "安全配置",
    },
    {
        "id": 12,
        "name": "配置Telnet远程登录",
        "prompt": "开启设备Telnet远程登录服务",
        "expected_keywords": ["telnet"],
        "category": "管理配置",
    },
    {
        "id": 13,
        "name": "配置SSH服务",
        "prompt": "配置设备SSH远程管理，使用RSA密钥认证",
        "expected_keywords": ["ssh"],
        "category": "管理配置",
    },
    {
        "id": 14,
        "name": "配置VRRP备份组",
        "prompt": "在Vlanif100接口上配置VRRP，虚拟IP为192.168.100.1，优先级120",
        "expected_keywords": ["interface Vlanif100", "vrrp", "192.168.100.1"],
        "category": "高可用",
    },
    {
        "id": 15,
        "name": "配置DHCP地址池",
        "prompt": "配置DHCP地址池，网段192.168.10.0/24，网关192.168.10.1，DNS 8.8.8.8",
        "expected_keywords": ["dhcp", "ip pool", "192.168.10."],
        "category": "服务配置",
    },
    {
        "id": 16,
        "name": "配置NAT静态转换",
        "prompt": "配置静态NAT，将内网192.168.1.10映射到公网203.0.113.10",
        "expected_keywords": ["nat static"],
        "category": "NAT配置",
    },
    {
        "id": 17,
        "name": "保存设备配置",
        "prompt": "保存当前设备配置",
        "expected_keywords": ["save"],
        "category": "基础配置",
    },
    {
        "id": 18,
        "name": "查看接口状态",
        "prompt": "查看所有接口的简要状态信息",
        "expected_keywords": ["display interface brief"],
        "category": "查询命令",
    },
    {
        "id": 19,
        "name": "查看路由表",
        "prompt": "查看设备的IP路由表",
        "expected_keywords": ["display ip routing-table"],
        "category": "查询命令",
    },
    {
        "id": 20,
        "name": "配置OSPF认证",
        "prompt": "为OSPF进程1的区域0配置MD5认证，密码使用占位符",
        "expected_keywords": ["ospf 1", "area 0", "authentication-mode"],
        "category": "路由协议",
    },
]


@dataclass
class EvalResult:
    """单条评估结果"""
    scenario_id: int
    scenario_name: str
    device_model: str
    category: str
    prompt: str
    commands: list = field(default_factory=list)
    explanation: str = ""
    warnings: list = field(default_factory=list)
    validation_results: list = field(default_factory=list)
    all_passed: bool = False
    high_risk_commands: list = field(default_factory=list)
    # 评估指标
    has_commands: bool = False
    keyword_hit_rate: float = 0.0
    validation_pass_rate: float = 0.0
    safety_filter_active: bool = False
    latency_ms: int = 0
    error: str = ""


def evaluate_scenario_static(scenario: dict, device_model: str, validator: VRPValidator) -> EvalResult:
    """静态评估：不调用LLM，仅验证预期命令的VRP合规性"""
    result = EvalResult(
        scenario_id=scenario["id"],
        scenario_name=scenario["name"],
        device_model=device_model,
        category=scenario["category"],
        prompt=scenario["prompt"],
    )

    expected_cmds = scenario["expected_keywords"]
    result.commands = expected_cmds
    result.has_commands = len(expected_cmds) > 0

    # VRP四层校验（对预期命令）
    config_text = "\n".join(expected_cmds)
    validation_results = validator.validate(config_text, device_model)
    result.validation_results = validation_results
    result.validation_pass_rate = (
        sum(1 for r in validation_results if r["passed"]) / len(validation_results)
        if validation_results else 1.0
    )
    result.all_passed = all(r["passed"] for r in validation_results) if validation_results else True

    # 高危命令检测
    high_risk = VRPValidator.check_high_risk_commands(config_text)
    result.high_risk_commands = high_risk
    result.safety_filter_active = len(high_risk) > 0

    return result


def evaluate_scenario_live(
    scenario: dict,
    device_model: str,
    validator: VRPValidator,
    llm_service,
) -> EvalResult:
    """实时评估：调用LLM生成命令，然后校验"""
    result = EvalResult(
        scenario_id=scenario["id"],
        scenario_name=scenario["name"],
        device_model=device_model,
        category=scenario["category"],
        prompt=scenario["prompt"],
    )

    start = time.time()
    try:
        # 调用LLM生成（同步包装）
        loop = asyncio.new_event_loop()
        gen_result = loop.run_until_complete(
            llm_service.generate_and_validate(scenario["prompt"], device_model)
        )
        loop.close()
        result.latency_ms = int((time.time() - start) * 1000)

        result.commands = gen_result.get("commands", [])
        result.explanation = gen_result.get("explanation", "")
        result.warnings = gen_result.get("warnings", [])
        result.validation_results = gen_result.get("validation_results", [])
        result.all_passed = gen_result.get("all_passed", False)
        result.high_risk_commands = gen_result.get("high_risk_commands", [])
        result.has_commands = len(result.commands) > 0

        # 关键词命中率
        hits = 0
        for keyword in scenario["expected_keywords"]:
            for cmd in result.commands:
                if keyword.lower() in cmd.lower():
                    hits += 1
                    break
        result.keyword_hit_rate = hits / len(scenario["expected_keywords"]) if scenario["expected_keywords"] else 0.0

        # 校验通过率
        if result.validation_results:
            result.validation_pass_rate = (
                sum(1 for r in result.validation_results if r["passed"]) / len(result.validation_results)
            )
        else:
            result.validation_pass_rate = 1.0

        result.safety_filter_active = any("拦截" in w for w in result.warnings)

    except Exception as e:
        result.error = str(e)
        result.latency_ms = int((time.time() - start) * 1000)

    return result


def generate_report(results: list) -> dict:
    """生成评估报告"""
    total = len(results)
    if total == 0:
        return {"error": "无评估结果"}

    # 总体指标
    has_commands_count = sum(1 for r in results if r.has_commands)
    avg_keyword_hit = sum(r.keyword_hit_rate for r in results) / total
    avg_validation_pass = sum(r.validation_pass_rate for r in results) / total
    all_passed_count = sum(1 for r in results if r.all_passed)
    error_count = sum(1 for r in results if r.error)
    avg_latency = sum(r.latency_ms for r in results) / total

    # 按设备型号分组
    by_model = {}
    for model in DEVICE_MODELS:
        model_results = [r for r in results if r.device_model == model]
        by_model[model] = {
            "total": len(model_results),
            "commands_generated": sum(1 for r in model_results if r.has_commands),
            "avg_keyword_hit_rate": round(sum(r.keyword_hit_rate for r in model_results) / len(model_results), 3) if model_results else 0,
            "avg_validation_pass_rate": round(sum(r.validation_pass_rate for r in model_results) / len(model_results), 3) if model_results else 0,
            "all_passed": sum(1 for r in model_results if r.all_passed),
            "errors": sum(1 for r in model_results if r.error),
        }

    # 按场景类别分组
    categories = set(r.category for r in results)
    by_category = {}
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        by_category[cat] = {
            "total": len(cat_results),
            "avg_keyword_hit_rate": round(sum(r.keyword_hit_rate for r in cat_results) / len(cat_results), 3) if cat_results else 0,
            "avg_validation_pass_rate": round(sum(r.validation_pass_rate for r in cat_results) / len(cat_results), 3) if cat_results else 0,
        }

    return {
        "summary": {
            "total_cases": total,
            "commands_generated_rate": round(has_commands_count / total, 3),
            "avg_keyword_hit_rate": round(avg_keyword_hit, 3),
            "avg_validation_pass_rate": round(avg_validation_pass, 3),
            "all_passed_rate": round(all_passed_count / total, 3),
            "error_rate": round(error_count / total, 3),
            "avg_latency_ms": round(avg_latency, 1),
        },
        "by_device_model": by_model,
        "by_category": by_category,
        "details": [asdict(r) for r in results],
    }


def run_static_eval() -> dict:
    """静态评估：验证20个场景的预期命令在3种设备型号上的VRP合规性"""
    validator = VRPValidator()
    results = []

    for model in DEVICE_MODELS:
        for scenario in SCENARIOS:
            result = evaluate_scenario_static(scenario, model, validator)
            results.append(result)

    return generate_report(results)


def run_live_eval() -> dict:
    """实时评估：调用LLM生成命令并校验"""
    # 延迟导入，避免静态评估时依赖LLM
    from modules.ai_text.llm_service import LLMService

    validator = VRPValidator()
    llm_service = LLMService()
    results = []

    total = len(DEVICE_MODELS) * len(SCENARIOS)
    count = 0

    for model in DEVICE_MODELS:
        for scenario in SCENARIOS:
            count += 1
            print(f"[{count}/{total}] {model} - {scenario['name']}...")
            result = evaluate_scenario_live(scenario, model, validator, llm_service)
            results.append(result)
            if result.error:
                print(f"  ERROR: {result.error}")
            else:
                print(f"  OK: {len(result.commands)} cmds, "
                      f"keyword={result.keyword_hit_rate:.0%}, "
                      f"validation={result.validation_pass_rate:.0%}, "
                      f"{result.latency_ms}ms")

    return generate_report(results)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AI配置生成准确率评估")
    parser.add_argument("--live", action="store_true", help="实时评估（调用LLM）")
    parser.add_argument("--output", type=str, default="ai_accuracy_report.json", help="输出文件")
    args = parser.parse_args()

    print("=" * 60)
    print("AI配置生成准确率评估")
    print(f"设备型号: {DEVICE_MODELS}")
    print(f"场景数: {len(SCENARIOS)}")
    print(f"总用例: {len(DEVICE_MODELS) * len(SCENARIOS)}")
    print("=" * 60)

    if args.live:
        print("\n[实时评估模式] 调用LLM生成命令...")
        report = run_live_eval()
    else:
        print("\n[静态评估模式] 验证预期命令的VRP合规性...")
        report = run_static_eval()

    # 输出报告
    output_path = Path(__file__).resolve().parent / args.output
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印摘要
    summary = report["summary"]
    print("\n" + "=" * 60)
    print("评估结果摘要")
    print("=" * 60)
    print(f"总用例数:          {summary['total_cases']}")
    print(f"命令生成率:        {summary['commands_generated_rate']:.1%}")
    print(f"平均关键词命中率:  {summary['avg_keyword_hit_rate']:.1%}")
    print(f"平均校验通过率:    {summary['avg_validation_pass_rate']:.1%}")
    print(f"全部通过率:        {summary['all_passed_rate']:.1%}")
    print(f"错误率:            {summary['error_rate']:.1%}")
    print(f"平均延迟:          {summary['avg_latency_ms']:.0f}ms")

    print("\n按设备型号:")
    for model, stats in report["by_device_model"].items():
        print(f"  {model}: 校验通过率={stats['avg_validation_pass_rate']:.1%}, "
              f"关键词命中={stats['avg_keyword_hit_rate']:.1%}")

    print("\n按场景类别:")
    for cat, stats in report["by_category"].items():
        print(f"  {cat}: 校验通过率={stats['avg_validation_pass_rate']:.1%}, "
              f"关键词命中={stats['avg_keyword_hit_rate']:.1%}")

    print(f"\n详细报告: {output_path}")


if __name__ == "__main__":
    main()
