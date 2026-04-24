"""
增量生成流程 - 自动分批输出用例，不受 max_tokens 限制

完全使用 Python 标准库，无第三方依赖

特点：
1. 对用户透明，自动分批
2. 每批独立生成，避免截断
3. 最终合并所有批次结果
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.api.llm_client import LLMClient


class IncrementalPipeline:
    """
    增量生成流程
    
    内部自动分批，对用户透明
    """

    def __init__(self, config: dict):
        self.config = config
        self.llm = LLMClient.from_config(config)
        
        # 加载提示词
        prompt_path = Path("prompts/system_prompt.md")
        if prompt_path.exists():
            self.system_prompt = prompt_path.read_text(encoding="utf-8")
        else:
            self.system_prompt = "你是一个测试用例生成专家。"

    def generate(
        self,
        requirement: str,
        example: str,
        target_count: int,
        batch_size: int = 7,
    ) -> Dict[str, Any]:
        """
        自动分批生成用例
        
        Args:
            requirement: 需求描述
            example: 示例用例
            target_count: 目标数量
            batch_size: 每批数量上限（会根据 token 限制自动调整）
            
        Returns:
            {
                "success": bool,
                "cases": List[Dict],      # 所有用例
                "batch_count": int,        # 总批次数
                "total_generated": int,    # 实际生成数量
                "error": str (可选)
            }
        """
        # 估算 prompt 长度，调整 batch_size
        prompt_text = requirement + "\n" + example
        prompt_tokens = self._estimate_tokens(prompt_text)
        
        # 根据 max_tokens 和 prompt 长度动态计算 batch_size
        max_output_tokens = self.config.get("llm", {}).get("max_tokens", 6000)
        available_tokens = (max_output_tokens - prompt_tokens) * 0.8
        tokens_per_case = 250
        dynamic_batch_size = max(2, min(batch_size, int(available_tokens // tokens_per_case)))
        
        all_cases = []
        batch_index = 0
        seen_ids = set()  # 用于去重
        actual_batch_size = min(batch_size, dynamic_batch_size)

        while len(all_cases) < target_count:
            remaining = target_count - len(all_cases)
            current_batch_size = min(actual_batch_size, remaining)

            result = self._generate_single_batch(
                requirement, example, current_batch_size, batch_index
            )

            if not result["success"]:
                # 如果第一批就失败，直接返回错误
                if batch_index == 0:
                    return {
                        "success": False,
                        "cases": [],
                        "batch_count": 0,
                        "total_generated": 0,
                        "error": result.get("error", "生成失败")
                    }
                # 后续批次失败，返回已生成的结果
                break

            # 添加用例，去重
            for case in result["cases"]:
                case_id = self._get_case_id(case)
                if case_id not in seen_ids:
                    seen_ids.add(case_id)
                    all_cases.append(case)

            batch_index += 1

            # 如果这批数量少于预期，说明可能已经到极限
            if result["batch_size"] < current_batch_size * 0.5:
                break

        return {
            "success": True,
            "cases": all_cases,
            "batch_count": batch_index,
            "total_generated": len(all_cases),
            "error": None
        }
    
    def _estimate_tokens(self, text: str) -> int:
        """估算 token 数量（中文优化版）"""
        if not text:
            return 0
        
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        chinese_tokens = chinese_chars / 1.8
        other_tokens = other_chars / 3.5
        
        return int(chinese_tokens + other_tokens)

    def _generate_single_batch(
        self,
        requirement: str,
        example: str,
        batch_size: int,
        batch_index: int,
    ) -> Dict[str, Any]:
        """
        生成单批用例
        
        Returns:
            {
                "success": bool,
                "cases": List[Dict],
                "batch_size": int,
                "error": str (可选)
            }
        """
        start_id = batch_index * batch_size + 2

        # 构建用户消息
        user_msg = self._build_user_message(
            requirement, example, batch_size, start_id
        )

        try:
            # 调用 LLM
            raw = self.llm.chat(self.system_prompt, user_msg)

            # 解析 JSON
            cases = self._parse_cases(raw, start_id)

            if not cases:
                return {
                    "success": False,
                    "cases": [],
                    "batch_size": 0,
                    "error": "无法解析用例"
                }

            return {
                "success": True,
                "cases": cases,
                "batch_size": len(cases),
                "error": None
            }

        except Exception as e:
            return {
                "success": False,
                "cases": [],
                "batch_size": 0,
                "error": str(e)
            }

    def _build_user_message(
        self, requirement: str, example: str, count: int, start_id: int
    ) -> str:
        """构建用户消息"""
        return f"""请根据以下需求生成 {count} 条测试用例。

【测试需求】
{requirement}

【示例用例格式】
{example}

请严格按照上述格式输出 {count} 条测试用例，每条用例必须包含所有字段。
用例编号从 TC_{start_id:03d} 开始。
只输出 JSON 数组，不要添加任何其他内容。"""

    def _parse_cases(self, raw: str, start_id: int) -> List[Dict[str, Any]]:
        """解析用例"""
        # 尝试直接解析
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return self._fix_ids(data, start_id)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        match = re.search(r"\[[\s\S]*\]", raw)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, list):
                    return self._fix_ids(data, start_id)
            except json.JSONDecodeError:
                pass

        return []

    def _fix_ids(self, cases: List[Dict], start_id: int) -> List[Dict[str, Any]]:
        """修正用例 ID"""
        for i, case in enumerate(cases):
            for key in case:
                if "id" in key.lower() or "编号" in key or "序号" in key:
                    case[key] = f"TC_{(start_id + i):03d}"
                    break
        return cases

    def _get_case_id(self, case: Dict) -> str:
        """获取用例 ID 用于去重"""
        for key, value in case.items():
            if "id" in key.lower() or "编号" in key or "序号" in key:
                return str(value)
        # 如果没有 ID，用内容的哈希
        return str(hash(str(case)))
