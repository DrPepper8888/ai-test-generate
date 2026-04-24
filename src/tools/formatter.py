"""
格式校验工具
校验 LLM 输出是否符合预期的 JSON 格式，并提取字段结构用于反馈重试
"""
import json
import re
from typing import Any, Optional, List


class FormatValidator:
    """校验并修复 LLM 生成的测试用例格式"""

    def extract_json(self, raw_text: str) -> Optional[List]:
        """从 LLM 原始输出中提取 JSON 数组"""
        text = raw_text.strip()

        # 策略 0：检查是否为空或几乎为空
        if not text or len(text) < 5:
            return None

        # 策略 1：直接解析
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError as e:
            pass

        # 策略 2：剥离 Markdown 代码围栏（改进：只匹配最外层的围栏）
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        fence_matches = list(re.finditer(fence_pattern, text, re.IGNORECASE))
        if fence_matches:
            # 优先使用最后一个完整的围栏块（通常 JSON 在最后）
            for match in reversed(fence_matches):
                content = match.group(1).strip()
                if len(content) > 10:  # 内容太短可能是误匹配
                    try:
                        data = json.loads(content)
                        if isinstance(data, list):
                            return data
                    except json.JSONDecodeError:
                        continue

        # 策略 3：找到第一个 [ 和对应的 ]（改进：使用栈来匹配括号）
        bracket_pairs = self._find_bracket_pair(text, '[', ']')
        if bracket_pairs:
            # 尝试每个可能的括号对
            for start, end in bracket_pairs:
                if end > start:
                    try:
                        data = json.loads(text[start: end + 1])
                        if isinstance(data, list):
                            return data
                    except json.JSONDecodeError:
                        continue

        return None

    def _find_bracket_pair(self, text: str, open_char: str, close_char: str) -> List[tuple]:
        """使用栈来找到所有匹配的括号对"""
        pairs = []
        stack = []
        
        for i, char in enumerate(text):
            if char == open_char:
                stack.append(i)
            elif char == close_char and stack:
                start = stack.pop()
                pairs.append((start, i))
        
        return pairs

    def extract_json_object(self, raw_text: str) -> Optional[dict]:
        """从 LLM 原始输出中提取 JSON 对象"""
        text = raw_text.strip()

        # 检查是否为空
        if not text or len(text) < 5:
            return None

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # 剥离 Markdown 代码围栏
        fence_matches = list(re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE))
        if fence_matches:
            for match in reversed(fence_matches):
                content = match.group(1).strip()
                if len(content) > 10:
                    try:
                        data = json.loads(content)
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        continue

        # 使用栈匹配括号
        brace_pairs = self._find_bracket_pair(text, '{', '}')
        if brace_pairs:
            for start, end in brace_pairs:
                if end > start:
                    try:
                        data = json.loads(text[start: end + 1])
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError:
                        continue

        return None

    def extract_fields_from_example(self, example_text: str) -> List[str]:
        """从示例用例文本中提取字段名列表"""
        example_text = example_text.strip()

        try:
            data = json.loads(example_text)
            if isinstance(data, dict):
                return list(data.keys())
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return list(data[0].keys())
        except (json.JSONDecodeError, TypeError):
            pass

        patterns = [
            r'^["\']?([^"\':\n]+)["\']?\s*[:：]',
            r'^["\']([^"\']+)["\']',
        ]
        fields = []
        for line in example_text.splitlines():
            line = line.strip().lstrip("{[, ").rstrip("}], ")
            for pattern in patterns:
                m = re.match(pattern, line)
                if m:
                    field_name = m.group(1).strip().strip("'\"")
                    if field_name and len(field_name) < 50:
                        fields.append(field_name)
                    break

        return fields

    def validate(self, cases: list, expected_fields: List[str]) -> dict:
        """校验用例列表是否符合格式要求"""
        errors = []
        missing_fields_all = set()

        if not isinstance(cases, list):
            return {"valid": False, "errors": ["输出不是 JSON 数组"], "missing_fields": []}

        if len(cases) == 0:
            return {"valid": False, "errors": ["生成了 0 条用例"], "missing_fields": []}

        for i, case in enumerate(cases):
            if not isinstance(case, dict):
                errors.append(f"第 {i+1} 条用例不是 JSON 对象")
                continue

            if expected_fields:
                case_fields = set(case.keys())
                expected_set = set(expected_fields)
                missing = expected_set - case_fields
                extra = case_fields - expected_set

                if missing:
                    missing_fields_all.update(missing)
                    errors.append(f"第 {i+1} 条用例缺少字段：{list(missing)}")

                if len(case_fields) != len(expected_set) and not missing:
                    errors.append(
                        f"第 {i+1} 条用例字段数量不匹配："
                        f"期望 {len(expected_set)} 个，实际 {len(case_fields)} 个"
                    )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "missing_fields": list(missing_fields_all),
        }

    def build_retry_feedback(self, validation_result: dict, expected_fields: List[str]) -> str:
        """构建反馈给 LLM 的重试提示"""
        lines = [
            "上一次的输出格式有误，请修正后重新生成：",
            "",
            "错误信息：",
        ]
        for err in validation_result["errors"]:
            lines.append(f"  - {err}")

        if validation_result["missing_fields"]:
            lines.append(f"\n必须包含的字段：{expected_fields}")
            lines.append(f"缺失的字段：{validation_result['missing_fields']}")

        lines.extend([
            "",
            "请严格按照示例用例的字段结构重新生成，输出纯 JSON 数组，不要添加任何额外文字。",
        ])
        return "\n".join(lines)
