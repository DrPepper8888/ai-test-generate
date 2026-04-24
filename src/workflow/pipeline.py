"""
状态机编排 — 串联完整生成流程
状态：IDLE → LOADING_PROMPT → BUILDING_PROMPT → CALLING_LLM → VALIDATING → DONE / ERROR
"""
import json
import os
import datetime
from typing import Optional
from pathlib import Path

from pathlib import Path
from src.api.llm_client import LLMClient
from src.api.llm_client import LLMError
from src.tools.formatter import FormatValidator
from src.tools.exporter import Exporter
from src.tools.deduplicator import deduplicate
from src.tools.quality_gate import QualityGate
from src.tools.quality_scorer import BatchQualityScorer
from src.tools.prompt_builder import PromptBuilder
from src.memory.memory_store import MemoryStore
from src.memory.rule_injector import RuleInjector
from src.workflow.expert_pipeline import ThreeExpertPipeline


class PipelineState:
    IDLE = "idle"
    LOADING_PROMPT = "loading_prompt"
    BUILDING_PROMPT = "building_prompt"
    CALLING_LLM = "calling_llm"
    VALIDATING = "validating"
    RETRYING = "retrying"
    DONE = "done"
    ERROR = "error"


class GenerationPipeline:
    """
    测试用例生成状态机
    负责编排：加载提示词 → 组装 Prompt → 调用 LLM → 格式校验 → 重试 → 输出
    """

    def __init__(self, config: dict):
        self.config = config
        self.llm = LLMClient.from_config(config)
        self.validator = FormatValidator()
        self.exporter = Exporter()
        self.quality_gate = QualityGate()
        self.quality_scorer = BatchQualityScorer()

        PROJECT_ROOT = Path(__file__).parent.parent.parent
        self.memory_store = MemoryStore(PROJECT_ROOT / "data")
        self.rule_injector = RuleInjector()
        self.prompt_builder = PromptBuilder(PROJECT_ROOT / "prompts")

        gen_cfg = config.get("generation", {})
        self.default_count = gen_cfg.get("default_count", 7)
        self.max_count = gen_cfg.get("max_count", 20)
        self.batch_size = gen_cfg.get("batch_size", 20)
        self.max_retries = gen_cfg.get("max_retries", 2)

        self._prompt_template: Optional[str] = None

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def run(
        self,
        requirement: str,
        example: str,
        count: int = 7,
        review_mode: bool = False,
        expert_mode: bool = False,
    ) -> dict:
        """
        执行完整生成流程

        Args:
            requirement: 测试需求描述
            example: 示例用例（JSON 格式字符串）
            count: 期望生成的用例数量
            review_mode: 是否启用双 Agent 评审（默认 False）
            expert_mode: 是否启用三专家模式（业务/边界/攻击串行生成）

        Returns:
            {
                'success': bool,
                'cases': list[dict],
                'markdown': str,
                'csv': str,
                'error': str,
                'state': str,
                'retries': int,
                'review': dict (当 review_mode=True 时),
                'expert_counts': dict (当 expert_mode=True 时),
            }
        """
        state = PipelineState.IDLE
        retries = 0

        try:
            # 三专家模式（串行调用三个专家）
            if expert_mode:
                return self._run_expert_mode(requirement, example, count, review_mode)

            # 原有单一生成模式
            # Step 1: 加载提示词模板
            state = PipelineState.LOADING_PROMPT
            system_prompt = self._load_system_prompt()

            # 提取示例字段结构（用于格式校验）
            expected_fields = self.validator.extract_fields_from_example(example)

            # Step 2: 处理分批逻辑（超过 batch_size 时分多次调用）
            count = max(1, min(count, self.max_count * 2))  # 允许最多 40 条
            all_cases = []
            start_id = 2  # TC_002 开始

            # 先构建一个临时用户消息用于 token 估算
            temp_user_msg = self._build_user_message(requirement, example, count, start_id)
            batches = self._split_into_batches(count, temp_user_msg)

            for batch_count in batches:
                state = PipelineState.BUILDING_PROMPT
                user_msg = self._build_user_message(
                    requirement, example, batch_count, start_id
                )

                # Step 3: 调用 LLM（含重试）
                batch_cases, batch_retries = self._call_with_retry(
                    system_prompt, user_msg, expected_fields, start_id
                )
                retries += batch_retries
                all_cases.extend(batch_cases)
                start_id += len(batch_cases)

            original_count = len(all_cases)
            all_cases = deduplicate(all_cases, scenario_type="general")
            deduplicated_count = original_count - len(all_cases)

            # 质量门禁检查
            quality_result = self.quality_gate.check_all(all_cases)
            if not quality_result["passed"]:
                # 如果有缺少场景，补充生成（最多重试1次）
                missing_scenarios = quality_result["missing_scenarios"]
                if missing_scenarios and retries < self.max_retries:
                    feedback = self.quality_gate.build_retry_feedback(quality_result)
                    supplementary_user_msg = (
                        self._build_user_message(requirement, example, max(2, len(missing_scenarios) * 2), start_id)
                        + "\n\n" + feedback
                    )
                    supplementary_cases, supplementary_retries = self._call_with_retry(
                        system_prompt, supplementary_user_msg, expected_fields, start_id
                    )
                    retries += supplementary_retries
                    all_cases.extend(supplementary_cases)
                    start_id += len(supplementary_cases)

                    # 再次去重
                    all_cases = deduplicate(all_cases, scenario_type="general")

            # 质量评分（在移除内部字段前，因为评分需要 _scenario）
            quality_score_result = self.quality_scorer.score_all(all_cases)
            all_cases = quality_score_result["cases"]

            # 移除内部字段（_scenario、_quality_score 等）
            all_cases = self.quality_gate.remove_internal_fields(all_cases)

            review_result = None
            if review_mode:
                review_result = self._review_cases(all_cases, example)

            state = PipelineState.DONE

            # 生成导出内容
            markdown = self.exporter.to_markdown(all_cases, requirement)
            csv_content = self.exporter.to_csv(all_cases)

            # 保存历史（异步性无所谓，P0 同步写即可）
            self._save_history(requirement, example, all_cases)

            result = {
                "success": True,
                "cases": all_cases,
                "markdown": markdown,
                "csv": csv_content,
                "error": None,
                "state": state,
                "retries": retries,
                "count": len(all_cases),
                "deduplicated": deduplicated_count,
                "quality_check": quality_result,
                "quality_score": {
                    "average_score": quality_score_result["average_score"],
                    "overall_level": quality_score_result["overall_level"],
                    "level_counts": quality_score_result["level_counts"],
                    "top_issues": quality_score_result["top_issues"],
                    "top_suggestions": quality_score_result["top_suggestions"],
                },
            }
            if review_result:
                result["review"] = review_result
            return result

        except LLMError as e:
            # LLM 调用错误（带分类）
            return self._error_result(
                message=str(e),
                state=state,
                retries=retries,
                error_type=e.error_type,
                error_details=e.details,
                error_suggestion=e.suggestion
            )
        except ConnectionError as e:
            return self._error_result(
                message=f"连接失败：{e}",
                state=state,
                retries=retries,
                error_type="CONNECTION_ERROR",
                error_details=str(e),
                error_suggestion="检查 LLM API 地址是否正确，网络是否正常"
            )
        except TimeoutError as e:
            return self._error_result(
                message=f"请求超时：{e}",
                state=state,
                retries=retries,
                error_type="TIMEOUT",
                error_details=str(e),
                error_suggestion="增加 config.json 中的 timeout 配置，或检查网络"
            )
        except Exception as e:
            return self._error_result(f"内部错误：{e}", state, retries)

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    def _load_system_prompt(self) -> str:
        """加载模块化提示词，并注入已学习的规则"""
        if self._prompt_template:
            return self._prompt_template

        # 使用模块化提示词构建器
        base_prompt = self.prompt_builder.build_base_prompt()

        # 注入规则（取最有效的前5条）
        rules = self.memory_store.get_effective_rules(top_k=5)
        self._prompt_template = self.prompt_builder.inject_learned_rules(base_prompt, rules)

        return self._prompt_template

    def _build_user_message(
        self, requirement: str, example: str, count: int, start_id: int
    ) -> str:
        """组装发给 LLM 的用户消息"""
        return PromptBuilder.build_user_message(requirement, example, count, start_id)

    def _load_review_prompt(self) -> str:
        """加载评审提示词"""
        candidates = [
            Path("prompts/review_prompt.md"),
            Path(__file__).parent.parent.parent / "prompts" / "review_prompt.md",
        ]
        for path in candidates:
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    def _review_cases(self, cases: list, example: str) -> dict:
        """评审用例质量"""
        review_prompt = self._load_review_prompt()
        if not review_prompt:
            return {"score": 0, "issues": ["评审提示词未找到"], "suggestions": []}

        user_msg = (
            f"【待评审用例】\n"
            f"{json.dumps(cases, ensure_ascii=False)}\n\n"
            f"【示例用例】\n{example}"
        )

        try:
            raw = self.llm.chat(review_prompt, user_msg)
            data = self.validator.extract_json_object(raw)
            if data is None:
                return {"score": 0, "issues": ["评审返回格式无效"], "suggestions": []}
            return {
                "score": data.get("score", 5),
                "issues": data.get("issues", []),
                "suggestions": data.get("suggestions", []),
            }
        except Exception as e:
            return {"score": 0, "issues": [str(e)], "suggestions": []}

    def _call_with_retry(
        self,
        system_prompt: str,
        user_msg: str,
        expected_fields: list,
        start_id: int,
    ) -> tuple[list, int]:
        """
        调用 LLM 并在格式校验失败时自动重试

        Returns:
            (用例列表, 重试次数)
        """
        retries = 0
        current_user_msg = user_msg

        last_raw = None  # 保存最后一次原始输出用于调试
        for attempt in range(self.max_retries + 1):
            raw = self.llm.chat(system_prompt, current_user_msg)
            last_raw = raw  # 保存用于错误报告

            # 解析 JSON
            cases = self.validator.extract_json(raw)
            if cases is None:
                if attempt < self.max_retries:
                    feedback = "输出格式错误：无法解析 JSON，请确保只输出纯 JSON 数组，不要添加任何其他文字或代码围栏。"
                    current_user_msg = user_msg + f"\n\n{feedback}"
                    retries += 1
                    continue
                else:
                    # 提供更详细的错误信息
                    error_detail = self._build_json_error_detail(raw)
                    raise RuntimeError(f"LLM 连续 {attempt+1} 次输出非法 JSON，已放弃\n\n{error_detail}")

            # 格式校验
            if expected_fields:
                validation = self.validator.validate(cases, expected_fields)
                if not validation["valid"] and attempt < self.max_retries:
                    feedback = self.validator.build_retry_feedback(validation, expected_fields)
                    current_user_msg = user_msg + f"\n\n{feedback}"
                    retries += 1
                    continue

            # 修正 ID（确保从正确的编号开始）
            cases = self._fix_ids(cases, start_id)
            return cases, retries

        return [], retries

    def _fix_ids(self, cases: list[dict], start_id: int) -> list[dict]:
        """修正用例 ID，确保从 TC_{start_id} 开始顺序编号"""
        # 找到第一个看起来像 ID 的字段
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

    def _estimate_tokens(self, text: str) -> int:
        """
        估算 token 数量
        中文约 1.5-2 字符/token，英文约 4 字符/token
        混合文本取中间值
        """
        if not text:
            return 0
        
        # 分别估算中英文字符数
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        
        # 中文 1.8 字符/token，英文/数字/符号 3.5 字符/token
        chinese_tokens = chinese_chars / 1.8
        other_tokens = other_chars / 3.5
        
        return int(chinese_tokens + other_tokens)

    def _split_into_batches(self, total_count: int, prompt_text: str = "") -> list[int]:
        """将总数量拆分为批次列表，基于精确 token 估算"""
        # 保守估计：prompt 占总 context 的 40%
        # 实际应该检查 model 的 context window，但暂时用这个估算
        prompt_tokens = self._estimate_tokens(prompt_text) if prompt_text else 0
        
        # 如果没有提供 prompt 文本，用经验值估算（一般 prompt 约 1000-2000 tokens）
        if prompt_tokens == 0:
            prompt_tokens = 1800
        
        # 考虑 system prompt（一般 500-1000 tokens）
        system_tokens = 800
        total_input_tokens = prompt_tokens + system_tokens
        
        # 从 config 获取 max_tokens 作为输出上限
        max_tokens = self.config.get("llm", {}).get("max_tokens", 6000)
        
        # 预留 20% buffer 防止截断
        available_output_tokens = (max_tokens - total_input_tokens) * 0.8
        
        # 每条用例约 150-300 tokens（中文字段多的话更多）
        tokens_per_case = 250
        
        max_cases_per_batch = max(1, int(available_output_tokens // tokens_per_case))
        max_cases_per_batch = min(max_cases_per_batch, self.batch_size)
        
        # 确保每批至少 2 条，太少效率低
        max_cases_per_batch = max(2, max_cases_per_batch)

        if total_count <= max_cases_per_batch:
            return [total_count]

        batches = []
        remaining = total_count
        while remaining > 0:
            batch = min(remaining, max_cases_per_batch)
            batches.append(batch)
            remaining -= batch
        return batches

    def _save_history(self, requirement: str, example: str, cases: list[dict]):
        """保存生成历史到 JSON 文件"""
        try:
            storage_cfg = self.config.get("storage", {})
            history_file = Path(storage_cfg.get("history_file", "data/history.json"))
            history_file.parent.mkdir(parents=True, exist_ok=True)

            history = []
            if history_file.exists():
                try:
                    history = json.loads(history_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    history = []

            record = {
                "id": len(history) + 1,
                "timestamp": datetime.datetime.now().isoformat(),
                "requirement": requirement[:200],
                "count": len(cases),
                "cases": cases,
            }
            history.append(record)

            history = history[-100:]
            history_file.write_text(
                json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass  # 历史保存失败不影响主流程

    def _build_json_error_detail(self, raw: str) -> str:
        """构建 JSON 解析错误的详细信息"""
        if not raw:
            return "LLM 返回内容为空"
        
        # 截取前300字符
        preview = raw[:300]
        if len(raw) > 300:
            preview += "..."
        
        return f"""【LLM 原始输出片段】
{preview}

【可能原因】
1. 输出包含代码围栏（如 ```json...```），需要去掉
2. 输出包含思考过程（如 <thinking>...</thinking>），需要移除
3. JSON 格式不完整或有多余字符
4. 输出被截断，请尝试减少生成数量"""

    def _error_result(self, message: str, state: str, retries: int, raw_output: str = None, error_type: str = None, error_details: str = None, error_suggestion: str = None) -> dict:
        """
        构建错误结果
        
        Args:
            message: 错误信息
            state: 当前状态
            retries: 重试次数
            raw_output: 原始 LLM 输出（如果有）
            error_type: 错误类型
            error_details: 错误详情
            error_suggestion: 解决建议
        """
        result = {
            "success": False,
            "cases": [],
            "markdown": "",
            "csv": "",
            "error": message,
            "state": state,
            "retries": retries,
            "count": 0,
        }
        
        # 添加错误类型分类
        if error_type:
            result["error_type"] = error_type
            result["error_details"] = error_details or ""
            result["error_suggestion"] = error_suggestion or ""
        
        # 添加原始输出用于调试（截取前500字符）
        if raw_output:
            result["debug"] = {
                "raw_output_preview": raw_output[:500] if len(raw_output) > 500 else raw_output,
                "raw_output_length": len(raw_output),
            }
        
        return result

    def get_history(self, limit: int = 20, offset: int = 0) -> list:
        """查询生成历史"""
        try:
            storage_cfg = self.config.get("storage", {})
            history_file = Path(storage_cfg.get("history_file", "data/history.json"))
            if not history_file.exists():
                return []

            history = json.loads(history_file.read_text(encoding="utf-8"))
            records = []
            for r in reversed(history[offset:offset+limit]):
                records.append({
                    "id": r.get("id"),
                    "timestamp": r.get("timestamp"),
                    "requirement": r.get("requirement"),
                    "count": r.get("count"),
                })
            return records
        except Exception:
            return []

    def get_history_detail(self, record_id: int) -> dict:
        """获取历史记录的详情"""
        try:
            storage_cfg = self.config.get("storage", {})
            history_file = Path(storage_cfg.get("history_file", "data/history.json"))
            if not history_file.exists():
                return {}

            history = json.loads(history_file.read_text(encoding="utf-8"))
            for r in history:
                if r.get("id") == record_id:
                    return r
            return {}
        except Exception:
            return {}

    def _run_expert_mode(
        self, requirement: str, example: str, count: int, review_mode: bool
    ) -> dict:
        """执行三专家串行生成模式"""
        from pathlib import Path
        PROJECT_ROOT = Path(__file__).parent.parent.parent

        # 加载规则
        rules = self.memory_store.load_rules()

        # 执行三专家串行生成
        expert_pipeline = ThreeExpertPipeline(self.config, PROJECT_ROOT)
        result = expert_pipeline.run(requirement, example, count, rules)

        all_cases = result["cases"]

        # 质量门禁检查
        quality_result = self.quality_gate.check_all(all_cases)
        if not quality_result["passed"]:
            # 如果有缺少场景，补充生成（最多重试1次）
            missing_scenarios = quality_result["missing_scenarios"]
            if missing_scenarios:
                # 调用对应领域的专家补充生成
                pass

        # 质量评分
        quality_score_result = self.quality_scorer.score_all(all_cases)
        all_cases = quality_score_result["cases"]

        # 移除内部字段
        all_cases = self.quality_gate.remove_internal_fields(all_cases)

        # 生成导出内容
        markdown = self.exporter.to_markdown(all_cases, requirement)
        csv_content = self.exporter.to_csv(all_cases)

        # 保存历史
        self._save_history(requirement, example, all_cases)

        review_result = None
        if review_mode:
            review_result = self._review_cases(all_cases, example)

        final_result = {
            "success": True,
            "cases": all_cases,
            "markdown": markdown,
            "csv": csv_content,
            "error": None,
            "state": PipelineState.DONE,
            "retries": 0,
            "count": len(all_cases),
            "deduplicated": result["deduplicated"],
            "expert_counts": result["expert_counts"],
            "quality_check": quality_result,
            "quality_score": {
                "average_score": quality_score_result["average_score"],
                "overall_level": quality_score_result["overall_level"],
                "level_counts": quality_score_result["level_counts"],
                "top_issues": quality_score_result["top_issues"],
                "top_suggestions": quality_score_result["top_suggestions"],
            },
            "expert_mode": True,
        }
        if review_result:
            final_result["review"] = review_result

        return final_result
