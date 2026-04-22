"""
质量门禁系统 — 测试用例生成质量检查
"""
from typing import List, Dict, Tuple


# 必须覆盖的场景类型
REQUIRED_SCENARIOS = {"normal", "boundary", "attack", "business"}

# 场景中文名
SCENARIO_NAMES = {
    "normal": "正常功能场景",
    "boundary": "边界值场景",
    "attack": "异常/攻击场景",
    "business": "特殊业务场景",
}


class QualityGate:
    """用例质量门禁"""

    def __init__(self):
        pass

    def check_all(self, cases: List[Dict]) -> Dict:
        """执行所有门禁检查
        Returns:
            {
                "passed": bool,
                "scenario_check": {...},
                "issues": list[str],
                "missing_scenarios": list[str],
            }
        """
        issues = []

        # 1. 场景覆盖检查
        scenario_result = self._check_scenario_coverage(cases)
        issues.extend(scenario_result["issues"])

        # 2. 字段完整性检查
        field_result = self._check_field_completeness(cases)
        issues.extend(field_result["issues"])

        return {
            "passed": len(issues) == 0,
            "scenario_check": scenario_result,
            "field_check": field_result,
            "issues": issues,
            "missing_scenarios": scenario_result["missing"],
        }

    def _check_scenario_coverage(self, cases: List[Dict]) -> Dict:
        """检查场景覆盖是否完整"""
        if not cases:
            return {
                "counts": {},
                "missing": list(REQUIRED_SCENARIOS),
                "coverage_rate": 0.0,
                "issues": ["用例列表为空"],
            }

        # 统计各场景数量
        scenario_counts = {}
        for case in cases:
            scenario = case.get("_scenario", "unknown")
            scenario_counts[scenario] = scenario_counts.get(scenario, 0) + 1

        # 检查缺少的场景
        existing_scenarios = set(scenario_counts.keys())
        missing = REQUIRED_SCENARIOS - existing_scenarios

        # 计算覆盖率
        coverage_rate = (len(REQUIRED_SCENARIOS) - len(missing)) / len(REQUIRED_SCENARIOS)

        # 生成问题列表
        issues = []
        if missing:
            missing_names = [SCENARIO_NAMES.get(s, s) for s in missing]
            issues.append(f"缺少场景覆盖：{'、'.join(missing_names)}")

        # 检查每类场景至少1条
        for scenario, count in scenario_counts.items():
            if scenario in REQUIRED_SCENARIOS and count < 1:
                issues.append(f"{SCENARIO_NAMES.get(scenario, scenario)} 数量不足")

        return {
            "counts": scenario_counts,
            "missing": list(missing),
            "coverage_rate": coverage_rate,
            "issues": issues,
        }

    def _check_field_completeness(self, cases: List[Dict]) -> Dict:
        """检查用例字段完整性"""
        if not cases:
            return {"empty_cases": 0, "issues": []}

        issues = []
        empty_count = 0

        # 检查每条用例的关键字段是否为空
        for i, case in enumerate(cases):
            for key, value in case.items():
                if key == "_scenario":
                    continue
                key_lower = key.lower()
                # 标题、预期结果这类关键字段不能为空
                if ("title" in key_lower or "标题" in key or "名称" in key or
                    "expected" in key_lower or "预期" in key):
                    if not value or not str(value).strip():
                        empty_count += 1
                        issues.append(f"用例 TC_{i+2:03d} 的 {key} 字段为空")
                        break

        return {
            "empty_cases": empty_count,
            "total_cases": len(cases),
            "issues": issues,
        }

    def build_retry_feedback(self, check_result: Dict) -> str:
        """生成重试反馈提示词"""
        if check_result["passed"]:
            return ""

        feedback_parts = ["【质量门禁检查不通过，请补充生成以下内容】"]

        # 缺少场景
        if check_result["missing_scenarios"]:
            feedback_parts.append("\n1. 请补充以下缺失场景的用例：")
            for s in check_result["missing_scenarios"]:
                feedback_parts.append(f"   - {SCENARIO_NAMES.get(s, s)}")

        # 其他问题
        if check_result["issues"]:
            feedback_parts.append("\n2. 请修正以下问题：")
            for issue in check_result["issues"]:
                feedback_parts.append(f"   - {issue}")

        feedback_parts.append("\n请直接输出补充的JSON数组，不要重复已有的用例。")

        return "\n".join(feedback_parts)

    def remove_internal_fields(self, cases: List[Dict]) -> List[Dict]:
        """移除用户不应该看到的内部字段（如 _scenario）"""
        cleaned = []
        for case in cases:
            cleaned_case = {k: v for k, v in case.items() if not k.startswith("_")}
            cleaned.append(cleaned_case)
        return cleaned