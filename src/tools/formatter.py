"""
格式校验工具
校验 LLM 输出是否符合预期的 JSON 格式，并提取字段结构用于反馈重试
"""
import json
import re
from typing import Any, Optional


class FormatValidator:
    """校验并修复 LLM 生成的测试用例格式"""

    def extract_json(self, raw_text: str) -> Optional[list]:
        """
        从 LLM 原始输出中提取 JSON 数组
        处理常见情况：带代码围栏、有额外文本、转义问题
        """
        text = raw_text.strip()

        # 策略 1：直接解析（模型输出纯净 JSON）
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # 策略 2：剥离 Markdown 代码围栏
        # 匹配 ```json ... ``` 或 ``` ... ```
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        fence_match = re.search(fence_pattern, text, re.IGNORECASE)
        if fence_match:
            try:
                data = json.loads(fence_match.group(1))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # 策略 3：找到第一个 [ 和最后一个 ] 之间的内容
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def extract_json_object(self, raw_text: str) -> Optional[dict]:
        """
        从 LLM 原始输出中提取 JSON 对象
        处理常见情况：带代码围栏、有额外文本、转义问题
        """
        text = raw_text.strip()

        # 策略 1：直接解析（模型输出纯净 JSON）
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # 策略 2：剥离 Markdown 代码围栏
        fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        fence_match = re.search(fence_pattern, text, re.IGNORECASE)
        if fence_match:
            try:
                data = json.loads(fence_match.group(1))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        # 策略 3：找到第一个 { 和最后一个 } 之间的内容
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def extract_fields_from_example(self, example_text: str) -> list[str]:
        """
        从示例用例文本中提取字段名列表
        支持 JSON 格式和键值对格式（如 "字段名: 值"）
        """
        example_text = example_text.strip()

        # 尝试 JSON 解析
        try:
            data = json.loads(example_text)
            if isinstance(data, dict):
                return list(data.keys())
            if isinstance(data, list) and data and isinstance(data[0], dict):
                return list(data[0].keys())
        except (json.JSONDecodeError, TypeError):
            pass

        # 尝试提取 "key: value" 或 "key：value" 格式的字段名
        patterns = [
            r'^["\']?([^"\':\n]+)["\']?\s*[:：]',  # key: value
            r'^["\']([^"\']+)["\']',               # "key"
        ]
        fields = []
        for line in example_text.splitlines():
            line = line.strip().lstrip("{[,").rstrip("}],")
            for pattern in patterns:
                m = re.match(pattern, line)
                if m:
                    field_name = m.group(1).strip().strip('"\'')
                    if field_name and len(field_name) < 50:
                        fields.append(field_name)
                    break

        return fields

    def validate(self, cases: list, expected_fields: list[str]) -> dict:
        """
        校验用例列表是否符合格式要求

        Returns:
            {
                'valid': bool,
                'errors': list[str],    # 错误描述列表
                'missing_fields': list  # 缺失字段
            }
        """
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

            # 检查字段数量是否一致（只校验数量和存在性，不校验字段名拼写）
            if expected_fields:
                case_fields = set(case.keys())
                expected_set = set(expected_fields)
                missing = expected_set - case_fields
                extra = case_fields - expected_set

                if missing:
                    missing_fields_all.update(missing)
                    errors.append(f"第 {i+1} 条用例缺少字段：{list(missing)}")

                # 字段数量不一致也报错（允许一点容差）
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

    def build_retry_feedback(self, validation_result: dict, expected_fields: list[str]) -> str:
        """
        构建反馈给 LLM 的重试提示
        """
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
