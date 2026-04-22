"""
导出工具
支持将测试用例导出为 Markdown 格式（P0），CSV/Excel 格式（P2 扩展预留）
"""
import json
import csv
import io
from typing import Optional


class Exporter:
    """测试用例导出器"""

    def to_markdown(
        self,
        cases: list[dict],
        requirement: str = "",
        example: str = "",
    ) -> str:
        """
        将测试用例列表导出为 Markdown 格式

        Args:
            cases: 测试用例列表（包含示例用例 TC_001）
            requirement: 需求描述（用于文档头部）
            example: 示例用例原文

        Returns:
            Markdown 格式字符串
        """
        if not cases:
            return "# 测试用例\n\n*暂无用例*\n"

        lines = ["# 测试用例生成结果", ""]

        if requirement:
            lines += ["## 需求描述", "", requirement, ""]

        lines += [f"**共生成 {len(cases)} 条用例**", ""]

        # 表格头
        fields = list(cases[0].keys())
        header = "| " + " | ".join(fields) + " |"
        separator = "| " + " | ".join(["---"] * len(fields)) + " |"
        lines += [header, separator]

        for case in cases:
            row_values = []
            for field in fields:
                val = case.get(field, "")
                # 转义 Markdown 表格中的竖线和换行
                val_str = str(val).replace("|", "\\|").replace("\n", "<br>")
                row_values.append(val_str)
            lines.append("| " + " | ".join(row_values) + " |")

        lines += ["", f"*生成工具：AI 测试用例生成器*"]
        return "\n".join(lines)

    def to_csv(self, cases: list[dict]) -> str:
        """
        将测试用例列表导出为 CSV 格式（使用 Python 标准库 csv 模块）

        Returns:
            CSV 格式字符串（UTF-8 with BOM，Excel 兼容）
        """
        if not cases:
            return ""

        output = io.StringIO()
        fields = list(cases[0].keys())
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(cases)

        # 添加 BOM 使 Excel 正确识别 UTF-8
        return "\ufeff" + output.getvalue()

    def to_json(self, cases: list[dict], indent: int = 2) -> str:
        """
        将测试用例列表导出为 JSON 格式
        """
        return json.dumps(cases, ensure_ascii=False, indent=indent)

    def merge_with_example(
        self, example_text: str, generated_cases: list[dict]
    ) -> list[dict]:
        """
        将示例用例（TC_001）与生成的用例合并为完整列表

        Args:
            example_text: 示例用例原文（JSON 格式）
            generated_cases: AI 生成的用例列表

        Returns:
            合并后的完整用例列表
        """
        try:
            example_data = json.loads(example_text.strip())
            if isinstance(example_data, dict):
                return [example_data] + generated_cases
            if isinstance(example_data, list):
                return example_data + generated_cases
        except (json.JSONDecodeError, TypeError):
            pass

        # 如果示例不是合法 JSON，直接返回生成的用例
        return generated_cases
