"""
三专家串行生成流水线
基于人格蒸馏理念：业务专家 → 边界专家 → 攻击专家 依次串行调用
"""
import json
from pathlib import Path
from typing import List, Dict

from src.api.llm_client import LLMClient
from src.tools.formatter import FormatValidator
from src.tools.deduplicator import deduplicate
from src.memory.rule_injector import RuleInjector


class ExpertGenerator:
    """单个专家生成器"""

    def __init__(self, llm_client: LLMClient, expert_name: str, prompt_path: str):
        self.llm = llm_client
        self.expert_name = expert_name
        self.prompt_path = prompt_path
        self.validator = FormatValidator()
        self.rule_injector = RuleInjector()
        self._base_prompt_cache = None  # 只缓存原始提示词，不缓存注入规则后的版本

    def load_prompt(self, rules: List[Dict] = None) -> str:
        """加载专家提示词，并动态注入已学习的规则
        注意：原始提示词会缓存，但规则是每次动态注入的，保证规则更新实时生效
        """
        if self._base_prompt_cache is None:
            path = Path(self.prompt_path)
            if path.exists():
                self._base_prompt_cache = path.read_text(encoding="utf-8")
            else:
                raise FileNotFoundError(f"找不到专家提示词：{self.prompt_path}")

        # 动态注入规则（每次调用都重新注入，保证规则更新实时生效）
        prompt = self._base_prompt_cache
        if rules:
            prompt = self.rule_injector.inject(prompt, rules)

        return prompt

    def generate(
        self,
        requirement: str,
        example: str,
        count: int,
        start_id: int,
        rules: List[Dict] = None,
    ) -> List[Dict]:
        """生成测试用例
        Args:
            requirement: 测试需求描述
            example: 示例用例
            count: 生成数量
            start_id: 起始ID编号
            rules: 已学习的规则列表
        Returns:
            生成的用例列表
        """
        system_prompt = self.load_prompt(rules)
        user_msg = (
            f"【测试需求描述】\n{requirement}\n\n"
            f"【示例用例】\n{example}\n\n"
            f"【生成数量】\n{count} 条\n"
            f"【ID起始编号】\nTC_{start_id:03d}\n\n"
            f"请严格按照示例用例的字段结构生成，输出纯 JSON 数组。"
        )

        raw = self.llm.chat(system_prompt, user_msg)
        cases = self.validator.extract_json(raw)

        if cases is None:
            return []

        # 修正ID
        cases = self._fix_ids(cases, start_id)
        return cases

    def _fix_ids(self, cases: List[Dict], start_id: int) -> List[Dict]:
        """修正用例 ID"""
        if not cases:
            return cases

        first = cases[0]
        id_field = None
        for key in first:
            key_lower = key.lower()
            if "id" in key_lower or "编号" in key or "序号" in key:
                id_field = key
                break

        if id_field is None:
            return cases

        for i, case in enumerate(cases):
            case[id_field] = f"TC_{(start_id + i):03d}"

        return cases


class ThreeExpertPipeline:
    """三专家串行生成流水线
    执行顺序：业务专家 → 边界专家 → 攻击专家
    """

    def __init__(self, config: dict, project_root: Path):
        self.config = config
        self.project_root = project_root
        self.llm = LLMClient.from_config(config)

        gen_cfg = config.get("generation", {})
        self.max_retries = gen_cfg.get("max_retries", 2)

        # 初始化三个专家（串行调用，每个专家生成后再调用下一个）
        expert_dir = project_root / "prompts" / "experts"
        self.business_expert = ExpertGenerator(
            self.llm, "business", str(expert_dir / "business_expert.md")
        )
        self.boundary_expert = ExpertGenerator(
            self.llm, "boundary", str(expert_dir / "boundary_expert.md")
        )
        self.attack_expert = ExpertGenerator(
            self.llm, "attack", str(expert_dir / "attack_expert.md")
        )

    def run(
        self,
        requirement: str,
        example: str,
        total_count: int = 9,
        rules: List[Dict] = None,
    ) -> Dict:
        """
        执行三专家串行生成
        Args:
            requirement: 测试需求描述
            example: 示例用例
            total_count: 总生成数量（平均分配给三个专家）
            rules: 已学习的规则列表
        Returns:
            {
                'success': bool,
                'cases': list[dict],
                'expert_counts': dict,
                'deduplicated': int,
            }
        """
        all_cases = []
        expert_counts = {}
        per_expert_count = max(2, total_count // 3)

        # 1. 业务专家生成（串行第一步）
        business_cases = self.business_expert.generate(
            requirement, example, per_expert_count, 2, rules
        )
        all_cases.extend(business_cases)
        expert_counts["business"] = len(business_cases)
        current_id = 2 + len(business_cases)

        # 2. 边界专家生成（串行第二步）
        boundary_cases = self.boundary_expert.generate(
            requirement, example, per_expert_count, current_id, rules
        )
        all_cases.extend(boundary_cases)
        expert_counts["boundary"] = len(boundary_cases)
        current_id += len(boundary_cases)

        # 3. 攻击专家生成（串行第三步）
        attack_cases = self.attack_expert.generate(
            requirement, example, per_expert_count, current_id, rules
        )
        all_cases.extend(attack_cases)
        expert_counts["attack"] = len(attack_cases)

        # 跨专家去重
        original_count = len(all_cases)
        all_cases = deduplicate(all_cases, scenario_type="general")
        deduplicated_count = original_count - len(all_cases)

        # 重新编号（保证ID连续）
        all_cases = self._renumber_ids(all_cases)

        return {
            "success": True,
            "cases": all_cases,
            "expert_counts": expert_counts,
            "deduplicated": deduplicated_count,
        }

    def _renumber_ids(self, cases: List[Dict]) -> List[Dict]:
        """重新编号，保证ID连续"""
        if not cases:
            return cases

        first = cases[0]
        id_field = None
        for key in first:
            key_lower = key.lower()
            if "id" in key_lower or "编号" in key or "序号" in key:
                id_field = key
                break

        if id_field is None:
            return cases

        for i, case in enumerate(cases):
            case[id_field] = f"TC_{(2 + i):03d}"

        return cases