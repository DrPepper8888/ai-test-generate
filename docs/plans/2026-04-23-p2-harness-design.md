# P2 Harness Engineering 重构设计方案

> 版本：v2.0 | 状态：✅ 已完成 Phase 1 | 日期：2026-04-24
> 作者：辛昊洋 | 审核：待确认

---

## 更新历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-04-23 | 初始设计方案 |
| v2.0 | 2026-04-24 | 增加自动学习系统（AI自审+三重质量保障） |

---

## 1. 背景与目标

### 1.1 项目背景

结合两篇文章的核心思想：

| 文章 | 核心观点 | 对应实现 |
|------|---------|---------|
| 测试新手用AI，先从测试点开始 | 先拆测试点，再生成用例 | 新增测试点拆解模式 |
| Harness Engineering | 错误沉淀到环境，规则持续进化 | 重构记忆系统 |

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| **G1** | 新增"测试点拆解"独立模式（2A） |
| **G2** | 重构记忆系统，支持规则半透明展示（1B） |
| **G3** | 建立可持续积累的规则库（3A，面向3B预留） |
| **G4** | 提升生成质量，降低用户纠错成本 |

### 1.3 非目标

- 不做用户认证系统（保持轻量）
- 不做多租户隔离（P0 先单机使用）
- 不做复杂的规则冲突检测（P1 先简单处理）

---

## 2. 整体架构

### 2.1 模块划分

```
┌─────────────────────────────────────────────────────────┐
│                     Web 层 (app.py)                     │
├─────────────────────────────────────────────────────────┤
│  API: /api/generate        → 生成用例                    │
│  API: /api/generate-points → 拆解测试点（新）            │
│  API: /api/feedback        → 提交反馈                    │
│  API: /api/rules           → 查询已学习规则（新）         │
├─────────────────────────────────────────────────────────┤
│                    Pipeline 层                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ TestPoints  │  │ Generation   │  │   Review    │     │
│  │   Pipeline  │  │   Pipeline   │  │   Pipeline  │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
├─────────────────────────────────────────────────────────┤
│                     Harness 层（新）                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ MemoryStore │  │RuleExtractor│  │RuleInjector │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
├─────────────────────────────────────────────────────────┤
│                     Tools 层                            │
│  FormatValidator │ Deduplicator │ Exporter │ Importer  │
├─────────────────────────────────────────────────────────┤
│                      API 层                             │
│                   LLMClient                              │
└─────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
用户输入需求
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│              1. 测试点拆解（可选，用户点击触发）           │
│   requirement ──▶ TestPointsPipeline ──▶ 测试点清单        │
│                            │                             │
│                            ▼                             │
│                      用户确认/修改                        │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│              2. Harness 注入规则                          │
│   rules.json ──▶ RuleInjector ──▶ 增强的 system_prompt   │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│              3. 用例生成                                  │
│   requirement + 测试点 + rules ──▶ GenerationPipeline   │
│                            │                            │
│                            ▼                            │
│                      用例列表                            │
└──────────────────────────┬───────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────┐
│              4. 用户反馈收集                             │
│   用户评价（好/差）──▶ RuleExtractor ──▶ rules.json      │
│                            │                            │
│                            ▼                            │
│                      规则进化                             │
└──────────────────────────────────────────────────────────┘
```

---

## 3. 新增功能：测试点拆解模式

### 3.1 API 规格

```
POST /api/generate-points

Request Body:
{
    "requirement": "优惠券下单功能，支持满减和新人券",
    "example": "[{\"title\": \"用例标题\", ...}]"  // 可选
}

Response:
{
    "success": true,
    "points": [
        {
            "id": "TP_001",
            "category": "正常流",
            "title": "用户使用满减券成功下单",
            "precondition": "用户已登录，购物车有商品，满足满减条件",
            "operation": "选择满减券，提交订单",
            "expected": "订单创建成功，优惠金额正确扣减",
            "risk_level": "P0"
        }
    ],
    "summary": "共拆解 12 个测试点，涵盖正常流/边界/异常/权限/数据一致性",
    "categories": {
        "正常流": 3,
        "边界值": 3,
        "异常流": 3,
        "权限差异": 2,
        "数据一致性": 1
    }
}
```

### 3.2 Prompt 模板

新增 `prompts/testpoints_prompt.md`:

```markdown
# 测试点拆解专家

你是一位资深的测试分析师，擅长将需求拆解为完整的测试点。

## 你的任务

根据用户提供的需求描述，按照以下五个维度拆解测试点：
1. **正常流**：用户顺利完成核心操作
2. **边界值**：输入边界、状态边界
3. **异常流**：错误处理、异常场景
4. **权限差异**：不同角色的操作差异
5. **数据一致性**：数据一致性、事务完整性

## 输出格式

请严格按照以下 JSON 数组格式输出，不要添加任何解释文字：

```json
[
  {
    "id": "TP_001",
    "category": "正常流",
    "title": "简洁的测试点标题",
    "precondition": "前置条件",
    "operation": "操作步骤",
    "expected": "预期结果",
    "risk_level": "P0"
  }
]
```

## 规则

- 每个测试点必须包含所有字段
- risk_level: P0=核心流程，P1=重要分支，P2=边缘场景
- 正常流至少 2 个，边界值至少 2 个
```

---

## 4. 重构记忆系统

### 4.1 核心数据结构

```python
# src/harness/models.py

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class RuleType(Enum):
    """规则类型"""
    FIELD_FORMAT = "field_format"           # 字段格式规范
    SCENARIO_COVERAGE = "scenario_coverage" # 场景覆盖
    BUSINESS_LOGIC = "business_logic"        # 业务逻辑
    BOUNDARY_VALUE = "boundary_value"        # 边界值
    RISK_ASSESSMENT = "risk_assessment"     # 风险评估
    GENERAL = "general"                     # 通用规则


class RuleLevel(Enum):
    """规则层级（预留多租户）"""
    GLOBAL = "global"      # 全局通用
    PROJECT = "project"   # 项目级
    USER = "user"         # 用户级


@dataclass
class Rule:
    """单条规则"""
    rule_id: str
    rule_text: str
    type: RuleType
    level: RuleLevel = RuleLevel.GLOBAL
    tags: List[str] = field(default_factory=list)
    source: str = ""
    source_detail: str = ""

    use_count: int = 0
    effective_count: int = 0
    ineffective_count: int = 0

    created_at: str = ""
    last_used_at: Optional[str] = None
    is_deprecated: bool = False

    @property
    def effective_rate(self) -> float:
        if self.use_count == 0:
            return 0.5
        return self.effective_count / self.use_count

    def is_worthy(self, min_use: int = 3) -> bool:
        if self.use_count < min_use:
            return True
        return self.effective_rate >= 0.3
```

### 4.2 MemoryStore 重构

```python
# src/harness/memory_store.py

import json
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import asdict

from src.harness.models import Rule, RuleType, RuleLevel


class MemoryStore:
    """记忆存储管理器 - Harness 的核心数据层"""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.memory_dir = self.data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.rules_path = self.memory_dir / "rules.json"
        self.interactions_dir = self.memory_dir / "interactions"
        self.annotated_path = self.memory_dir / "annotated_cases.json"

        self.interactions_dir.mkdir(exist_ok=True)

    def load_rules(self, level: RuleLevel = None) -> List[Rule]:
        if not self.rules_path.exists():
            return []
        try:
            data = json.loads(self.rules_path.read_text(encoding="utf-8"))
            rules = [Rule(**r) for r in data]
            if level:
                rules = [r for r in rules if r.level == level]
            return rules
        except (json.JSONDecodeError, OSError, TypeError):
            return []

    def save_rules(self, rules: List[Rule]):
        data = [asdict(r) for r in rules]
        self.rules_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def add_rule(
        self,
        rule_text: str,
        rule_type: RuleType,
        source: str,
        source_detail: str = "",
        tags: List[str] = None,
    ) -> str:
        rules = self.load_rules()
        for existing in rules:
            if existing.rule_text == rule_text:
                return existing.rule_id

        max_id = max(
            (int(r.rule_id.replace("RULE_", "")) for r in rules if r.rule_id.startswith("RULE_")),
            default=0
        )

        rule = Rule(
            rule_id=f"RULE_{max_id + 1:04d}",
            rule_text=rule_text,
            type=rule_type,
            level=RuleLevel.GLOBAL,
            tags=tags or [],
            source=source,
            source_detail=source_detail,
            created_at=self._now(),
        )

        rules.append(rule)
        self.save_rules(rules)
        return rule.rule_id

    def record_feedback(self, rule_id: str, is_effective: bool, feedback: str = ""):
        rules = self.load_rules()
        for rule in rules:
            if rule.rule_id == rule_id:
                rule.use_count += 1
                if is_effective:
                    rule.effective_count += 1
                else:
                    rule.ineffective_count += 1
                rule.last_used_at = self._now()
                break
        self.save_rules(rules)

    def get_effective_rules(self, top_k: int = 5) -> List[Rule]:
        rules = [r for r in self.load_rules() if not r.is_deprecated]
        scored = []
        for r in rules:
            rate = r.effective_rate
            if r.use_count < 3:
                rate = max(rate, 0.3)
            scored.append((r, rate))
        scored.sort(key=lambda x: (-x[1], -x[0].use_count))
        return [r for r, _ in scored[:top_k]]

    def get_rules_for_display(self, limit: int = 20) -> List[Dict]:
        rules = self.get_effective_rules(top_k=limit)
        return [
            {
                "id": r.rule_id,
                "text": r.rule_text,
                "type": r.type.value,
                "source": r.source,
                "stats": {
                    "used": r.use_count,
                    "effective": r.effective_count,
                    "rate": round(r.effective_rate * 100, 1),
                }
            }
            for r in rules
        ]

    def cleanup_rules(self) -> int:
        rules = self.load_rules()
        deprecated = 0
        for rule in rules:
            if rule.use_count >= 5 and rule.effective_rate < 0.3:
                rule.is_deprecated = True
                deprecated += 1
        if deprecated > 0:
            self.save_rules(rules)
        return deprecated

    @staticmethod
    def _now() -> str:
        from datetime import datetime
        return datetime.now().isoformat()
```

### 4.3 RuleExtractor 重构

```python
# src/harness/rule_extractor.py

import json
from typing import List, Dict
from src.api.llm_client import LLMClient
from src.harness.models import RuleType


EXTRACT_FROM_FEEDBACK_PROMPT = """
# 规则提取专家

你是一位专业的测试规则提取工程师。你的任务是从用户反馈中提取可复用的测试规则。

## 用户反馈

```
{feedback}
```

## 任务

1. 仔细阅读用户反馈，判断这是否是可复用的规则
2. 提取 1-3 条可复用的规则

## 输出格式

```json
[
  {
    "rule_text": "规则内容（简洁、可执行）",
    "type": "field_format | scenario_coverage | business_logic | boundary_value | general",
    "reasoning": "为什么提取这条规则"
  }
]
```

请只输出 JSON，不要添加任何解释。
"""


EXTRACT_FROM_GOOD_CASES_PROMPT = """
# 优质用例反向学习

你是一位测试规则提取专家。请分析以下被标记为"优质"的测试用例，提取可复用的编写规则。

## 优质用例

```json
{cases_json}
```

## 任务

提取 3-5 条最有价值的通用规则，关注：
- 字段填写规范
- 描述粒度
- 场景覆盖方法
- 预期结果写法

## 输出格式

```json
[
  {
    "rule_text": "规则内容",
    "type": "writing_style | scenario_coverage | general",
    "reasoning": "为什么提取这条规则"
  }
]
```

请只输出 JSON，不要添加任何解释。
"""


class RuleExtractor:
    """规则提取器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def extract_from_feedback(self, feedback: str) -> List[Dict]:
        prompt = EXTRACT_FROM_FEEDBACK_PROMPT.format(feedback=feedback)
        raw = self.llm.chat(prompt, "")
        return self._parse_json(raw)

    def extract_from_good_cases(self, cases: List[Dict]) -> List[Dict]:
        if len(cases) < 3:
            return []
        cases_json = json.dumps(cases, ensure_ascii=False, indent=2)
        prompt = EXTRACT_FROM_GOOD_CASES_PROMPT.format(cases_json=cases_json)
        raw = self.llm.chat(prompt, "")
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> List[Dict]:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            import re
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return []
```

### 4.4 RuleInjector 重构

```python
# src/harness/rule_injector.py

from typing import List
from src.harness.models import Rule


SYSTEM_RULE_PREFIX = """
---
【已学习规则】（来自历史反馈，越用越准）
"""

SYSTEM_RULE_SUFFIX = """
---
"""


class RuleInjector:
    """规则注入器"""

    @staticmethod
    def inject(system_prompt: str, rules: List[Rule], top_n: int = 5) -> str:
        if not rules:
            return system_prompt

        sorted_rules = sorted(rules, key=lambda r: r.use_count, reverse=True)
        selected = sorted_rules[:top_n]

        rules_text = SYSTEM_RULE_PREFIX
        for i, rule in enumerate(selected, 1):
            rules_text += f"\n{i}. {rule.rule_text}（类型：{rule.type.value}）"
        rules_text += SYSTEM_RULE_SUFFIX

        return rules_text + "\n\n" + system_prompt

    @staticmethod
    def get_display_text(rules: List[Rule]) -> str:
        if not rules:
            return "暂无已学习规则，继续生成用例来培养它吧！"
        lines = []
        for i, rule in enumerate(rules, 1):
            lines.append(f"{i}. {rule.rule_text}")
        return "\n".join(lines)
```

---

## 5. Pipeline 集成

### 5.1 新增 TestPointsPipeline

```python
# src/workflow/testpoints_pipeline.py

import json
from pathlib import Path
from src.api.llm_client import LLMClient
from src.tools.formatter import FormatValidator


class TestPointsPipeline:
    """测试点拆解流程"""

    def __init__(self, config: dict):
        self.llm = LLMClient.from_config(config)
        self.prompt_path = Path("prompts/testpoints_prompt.md")
        self.validator = FormatValidator()

    def run(self, requirement: str, example: str = None) -> dict:
        # 1. 加载提示词
        prompt = self.prompt_path.read_text(encoding="utf-8")

        # 2. 组装用户消息
        user_msg = f"【测试需求】\n{requirement}"
        if example:
            user_msg += f"\n\n【参考示例】\n{example}"

        # 3. 调用 LLM
        raw = self.llm.chat(prompt, user_msg)

        # 4. 解析结果
        points = self._parse_points(raw)

        # 5. 统计分析
        categories = self._count_by_category(points)
        summary = f"共拆解 {len(points)} 个测试点，涵盖正常流/边界/异常/权限/数据一致性"

        return {
            "success": True,
            "points": points,
            "summary": summary,
            "categories": categories
        }

    def _parse_points(self, raw: str) -> List[Dict]:
        """解析测试点"""
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            import re
            match = re.search(r"\[[\s\S]*\]", raw)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return []

    def _count_by_category(self, points: List[Dict]) -> Dict[str, int]:
        """按类别统计"""
        counts = {}
        for p in points:
            cat = p.get("category", "其他")
            counts[cat] = counts.get(cat, 0) + 1
        return counts
```

### 5.2 集成到 app.py

```python
# web/app.py 新增路由

# 测试点拆解
class GeneratePointsHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # 解析请求
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        data = json.loads(body)

        requirement = data.get("requirement", "")
        example = data.get("example")

        # 调用 Pipeline
        from src.workflow.testpoints_pipeline import TestPointsPipeline
        pipeline = TestPointsPipeline(self.server.config)

        result = pipeline.run(requirement, example)

        # 返回结果
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode("utf-8"))


# 查询已学习规则
class RulesHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        from src.harness.memory_store import MemoryStore
        from pathlib import Path

        store = MemoryStore(Path("data"))
        rules = store.get_rules_for_display(limit=20)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"success": True, "rules": rules}).encode("utf-8"))


# 注册路由
HANDLERS = {
    "/": IndexHandler,
    "/api/generate": GenerateHandler,
    "/api/generate-points": GeneratePointsHandler,  # 新增
    "/api/feedback": FeedbackHandler,
    "/api/rules": RulesHandler,  # 新增
}
```

---

## 6. 前端 UI 改动

### 6.1 新增"测试点拆解"按钮

```html
<!-- index.html 新增 -->

<div class="mode-selector">
    <label>
        <input type="radio" name="mode" value="direct" checked>
        直接生成用例
    </label>
    <label>
        <input type="radio" name="mode" value="points-first">
        先拆测试点（推荐新手）
    </label>
</div>

<!-- 测试点结果显示区（默认隐藏） -->
<div id="testpoints-section" style="display: none;">
    <h3>测试点清单</h3>
    <div id="testpoints-list"></div>
    <button id="confirm-points">确认后生成用例</button>
</div>
```

### 6.2 已学习规则展示

```html
<!-- index.html 新增 -->

<div class="harness-panel">
    <h3>🦆 Harness 进化状态</h3>
    <p>已学习 <span id="rule-count">0</span> 条规则</p>
    <div id="rules-list">
        <!-- 动态加载 -->
    </div>
</div>
```

---

## 7. 实施计划

### 7.1 任务清单

| 序号 | 任务 | 预估时间 | 依赖 |
|------|------|---------|------|
| T1 | 创建 src/harness/ 目录结构 | 10min | - |
| T2 | 实现 src/harness/models.py | 15min | T1 |
| T3 | 重构 src/harness/memory_store.py | 30min | T2 |
| T4 | 重构 src/harness/rule_extractor.py | 20min | T3 |
| T5 | 重构 src/harness/rule_injector.py | 15min | T3 |
| T6 | 新增 prompts/testpoints_prompt.md | 10min | - |
| T7 | 实现 src/workflow/testpoints_pipeline.py | 30min | T6 |
| T8 | 新增 /api/generate-points API | 20min | T7 |
| T9 | 新增 /api/rules API | 15min | T3 |
| T10 | 前端 UI 改动 | 40min | T8, T9 |
| T11 | 集成测试 | 30min | T10 |
| T12 | 更新文档 | 20min | - |

### 7.2 里程碑

| 阶段 | 内容 | 目标 |
|------|------|------|
| **M1** | Harness 核心完成 | T1-T5 |
| **M2** | 测试点模式完成 | T6-T9 |
| **M3** | 前后端联调完成 | T10-T11 |
| **M4** | 文档和发布 | T12 |

**总预估工时：约 4-5 小时**

---

## 8. 测试计划

### 8.1 单元测试

```python
# test/harness/test_memory_store.py

def test_add_rule():
    store = MemoryStore(Path("data/test_memory"))
    rule_id = store.add_rule(
        rule_text="测试用例必须包含前置条件",
        rule_type=RuleType.FIELD_FORMAT,
        source="用户反馈"
    )
    assert rule_id.startswith("RULE_")

def test_feedback_recording():
    store = MemoryStore(Path("data/test_memory"))
    rule_id = store.add_rule("测试规则", RuleType.GENERAL, "test")

    store.record_feedback(rule_id, is_effective=True)
    store.record_feedback(rule_id, is_effective=True)
    store.record_feedback(rule_id, is_effective=False)

    rules = store.load_rules()
    rule = next(r for r in rules if r.rule_id == rule_id)
    assert rule.use_count == 3
    assert rule.effective_count == 2

def test_effective_rules_ranking():
    store = MemoryStore(Path("data/test_memory"))
    # ... 添加不同有效率的规则 ...
    effective = store.get_effective_rules(top_k=3)
    # 验证排序正确
```

### 8.2 E2E 测试

```
1. 调用 /api/generate-points → 验证返回测试点
2. 调用 /api/generate → 验证规则被注入
3. 调用 /api/feedback → 验证规则更新
4. 调用 /api/rules → 验证规则展示
5. 多次循环 → 验证规则进化
```

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| LLM 规则提取质量不稳定 | 规则错误 | P1 先人工审核，后期开放自动 |
| 规则冲突 | 生成质量下降 | P1 先简单去重，P2 做冲突检测 |
| 数据迁移 | 历史数据丢失 | 先备份，再迁移 |
| 性能下降 | API 响应慢 | 规则缓存，减少 LLM 调用 |

---

## 10. 后续迭代方向

### P2（未来）

- 用户画像 + 个性化规则推荐
- 多项目规则隔离
- 规则冲突检测

### P3（远期）

- 主动学习：自动发现高质量用例
- 规则版本管理
- 团队协作规则分享

---

*文档版本：v2.0 | 最后更新：2026-04-23*
