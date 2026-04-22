"""
用例质量自动评分系统
对生成的测试用例进行多维度打分
"""
import re
from typing import List, Dict, Tuple


class CaseQualityScorer:
    """单条用例质量评分器"""

    def __init__(self):
        # 常见动词（用于判断步骤描述质量）
        self.action_verbs = {
            "点击", "输入", "选择", "提交", "确认", "取消", "打开",
            "关闭", "查看", "编辑", "删除", "修改", "更新", "上传",
            "下载", "导出", "导入", "搜索", "筛选", "排序"
        }

    def score_case(self, case: Dict) -> Dict:
        """对单条用例进行综合评分
        Returns:
            {
                "total_score": 0-100,
                "dimensions": {
                    "format": 0-30,      # 格式完整性
                    "scenario": 0-30,    # 场景清晰度
                    "clarity": 0-20,     # 描述清晰度
                    "boundary": 0-20,    # 边界值覆盖
                },
                "issues": list[str],
                "suggestions": list[str],
            }
        """
        issues = []
        suggestions = []

        # 1. 格式完整性（30分）
        format_score = self._score_format(case, issues, suggestions)

        # 2. 场景清晰度（30分）
        scenario_score = self._score_scenario(case, issues, suggestions)

        # 3. 描述清晰度（20分）
        clarity_score = self._score_clarity(case, issues, suggestions)

        # 4. 边界值（20分）
        boundary_score = self._score_boundary(case, issues, suggestions)

        total = format_score + scenario_score + clarity_score + boundary_score

        return {
            "total_score": total,
            "dimensions": {
                "format": format_score,
                "scenario": scenario_score,
                "clarity": clarity_score,
                "boundary": boundary_score,
            },
            "level": self._score_to_level(total),
            "issues": issues,
            "suggestions": suggestions,
        }

    def _score_format(self, case: Dict, issues: list, suggestions: list) -> int:
        """格式完整性评分（0-30）"""
        score = 30

        # 检查字段非空
        empty_fields = []
        for key, value in case.items():
            if key.startswith("_"):
                continue
            if not value or not str(value).strip():
                empty_fields.append(key)

        if empty_fields:
            score -= len(empty_fields) * 5
            issues.append(f"字段为空：{', '.join(empty_fields)}")

        # 检查关键字段是否存在
        required_keywords = ["title", "标题", "expected", "预期", "步骤", "steps"]
        found_keywords = set()
        for key in case:
            key_lower = key.lower()
            for kw in required_keywords:
                if kw in key_lower:
                    found_keywords.add(kw)

        missing = len(required_keywords) - len(found_keywords)
        if missing > 0:
            score -= missing * 3
            issues.append(f"缺少关键字段：{', '.join(set(required_keywords) - found_keywords)}")

        return max(0, score)

    def _score_scenario(self, case: Dict, issues: list, suggestions: list) -> int:
        """场景清晰度评分（0-30）"""
        score = 30
        all_text = " ".join(str(v) for v in case.values()).lower()

        # 检查是否有模糊词
        vague_words = ["正常", "正确", "一般", "通常", "普通"]
        vague_count = sum(1 for w in vague_words if w in all_text)

        if vague_count > 2:
            score -= vague_count * 3
            suggestions.append(f"用例描述包含{vague_count}个模糊词，建议更具体描述测试场景")

        # 检查是否有具体的测试目标
        if len(all_text) < 20:
            score -= 15
            issues.append("用例描述过短，测试目标不明确")

        return max(0, score)

    def _score_clarity(self, case: Dict, issues: list, suggestions: list) -> int:
        """描述清晰度评分（0-20）"""
        score = 20
        all_text = " ".join(str(v) for v in case.values())

        # 检查步骤是否有动词开头
        has_action = any(verb in all_text for verb in self.action_verbs)
        if not has_action:
            score -= 10
            suggestions.append("测试步骤建议使用动词开头（如：点击、输入、选择...）")

        # 检查预期结果是否可验证
        expected_keywords = ["显示", "提示", "成功", "失败", "返回", "跳转", "出现", "保存"]
        has_expected_kw = any(kw in all_text for kw in expected_keywords)
        if not has_expected_kw:
            score -= 10
            suggestions.append("预期结果建议包含可验证的结果描述（如：显示成功、提示错误...）")

        return max(0, score)

    def _score_boundary(self, case: Dict, issues: list, suggestions: list) -> int:
        """边界值评分（0-20）"""
        score = 20
        all_text = " ".join(str(v) for v in case.values()).lower()

        boundary_keywords = [
            "最大", "最小", "临界", "空", "0", "超长", "超短",
            "边界", "极限", "异常", "错误", "非法", "超时"
        ]
        has_boundary = any(kw in all_text for kw in boundary_keywords)

        # 这个维度主要针对边界场景用例，正常场景不扣分
        scenario = case.get("_scenario", "")
        if scenario == "boundary" and not has_boundary:
            score -= 15
            issues.append("边界场景用例缺少边界值描述")
        elif scenario in ["normal", "business"]:
            # 正常场景不要求边界词，给基础分
            pass
        else:
            # 未知场景适当扣分
            score -= 5

        return max(0, score)

    @staticmethod
    def _score_to_level(score: int) -> str:
        """分数转等级"""
        if score >= 90:
            return "S"
        elif score >= 80:
            return "A"
        elif score >= 70:
            return "B"
        elif score >= 60:
            return "C"
        else:
            return "D"


class BatchQualityScorer:
    """批量用例质量评分器"""

    def __init__(self):
        self.single_scorer = CaseQualityScorer()

    def score_all(self, cases: List[Dict]) -> Dict:
        """批量评分
        Returns:
            {
                "cases": list[带评分的用例],
                "average_score": float,
                "level_counts": dict,
                "overall_issues": list[str],
                "overall_suggestions": list[str],
            }
        """
        if not cases:
            return {
                "cases": [],
                "average_score": 0,
                "level_counts": {},
                "overall_issues": [],
                "overall_suggestions": [],
            }

        scored_cases = []
        total_score = 0
        level_counts = {"S": 0, "A": 0, "B": 0, "C": 0, "D": 0}
        all_issues = []
        all_suggestions = []

        for case in cases:
            score_result = self.single_scorer.score_case(case)
            scored_case = case.copy()
            scored_case["_quality_score"] = score_result
            scored_cases.append(scored_case)

            total_score += score_result["total_score"]
            level_counts[score_result["level"]] += 1
            all_issues.extend(score_result["issues"])
            all_suggestions.extend(score_result["suggestions"])

        # 统计最常见的问题和建议
        from collections import Counter
        top_issues = [item[0] for item in Counter(all_issues).most_common(5)]
        top_suggestions = [item[0] for item in Counter(all_suggestions).most_common(5)]

        average = total_score / len(cases)

        return {
            "cases": scored_cases,
            "average_score": round(average, 1),
            "overall_level": CaseQualityScorer._score_to_level(int(average)),
            "level_counts": level_counts,
            "top_issues": top_issues,
            "top_suggestions": top_suggestions,
        }
