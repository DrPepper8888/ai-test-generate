# 自动学习规则系统 - 详细设计方案

> 版本：v2.0 | 状态：✅ Phase 1 & 2 & 3 完成 | 日期：2026-04-24
> 作者：辛昊洋

---

## 更新历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-04-24 | 完成详细设计 + Phase 1 + Phase 2 + Phase 3 实现 |

让规则学习**零操作、零感知、持续进化**，同时保证规则质量可控。

---

## 2. 整体架构

```
用户操作
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                    自动学习流程（后台）                        │
│                                                              │
│  用户给反馈（👍/👎）                                          │
│        │                                                     │
│        ▼                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │  AI 自审    │───▶│  规则提取   │───▶│  规则入库   │      │
│  │ (Option 3) │    │ (Option 1)  │    │             │      │
│  └─────────────┘    └─────────────┘    └──────┬──────┘      │
│        │                                        │             │
│        ▼                                        ▼             │
│  淘汰明显错误          ┌─────────────────────────────┐        │
│  的规则                │  规则库 rules.json          │        │
│                        └─────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    三重质量保障                               │
│                                                              │
│  ① AI 自审    ───  学习前过滤明显错误的规则                    │
│  ② 自动淘汰   ───  使用5次后有效率<30% → is_deprecated=true   │
│  ③ 手动管理   ───  用户可在规则管理页面删除/编辑/禁用规则       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 详细设计

### 3.1 自动学习流程

#### 触发时机

| 场景 | 是否触发 | 说明 |
|------|---------|------|
| 生成完成 + 用户给 👍 | ✅ 触发 | 正向反馈 → 学习优质用例特征 |
| 生成完成 + 用户给 👎 | ✅ 触发 | 负向反馈 → 学习避免错误 |
| 用户点击「📚 学习规则」| ✅ 触发 | 手动触发 → 从所有标注学习 |
| 无反馈直接生成新用例 | ❌ 不触发 | 没有反馈就没法学习 |

#### 学习内容

```python
# 从两种来源学习

# 来源 1：从反馈文本学习
feedback = "用例 TC_003 的预期结果不对，应该是..."
rules_from_feedback = extractor.extract_from_feedback(feedback)

# 来源 2：从优质用例反向学习
good_cases = [case for case in session.cases if label == "accepted"]
rules_from_cases = extractor.extract_from_good_cases(good_cases)

# 合并 + 去重
all_new_rules = merge_rules(existing_rules, rules_from_feedback + rules_from_cases)
```

### 3.2 AI 自审（Option 3）

在规则入库前，先让 AI 评估规则质量：

```python
RULE_QUALITY_CHECK_PROMPT = """
你是一位规则质量审核员。请评估以下规则是否值得入库。

【候选规则】
{rule_text}

【评估维度】
1. 可执行性：规则是否可以指导生成动作？
2. 可复用性：规则是否通用，不是针对具体案例？
3. 清晰度：规则表述是否清晰无歧义？

【输出格式】
```json
{
  "approve": true/false,
  "reason": "审核理由",
  "improved_text": "如果表述不清，给出改进版本"
}
```

请只输出 JSON。
"""
```

**过滤逻辑：**
```python
for rule in candidate_rules:
    quality = ai_check_rule_quality(rule["rule_text"])
    if quality["approve"]:
        rule["rule_text"] = quality.get("improved_text", rule["rule_text"])
        rules.append(rule)  # 入库
    else:
        discarded.append(rule)  # 丢弃并记录原因
```

### 3.3 自动淘汰（Option 1）

```python
# 使用规则时检查
def check_and_deprecate_rules(rules: List[Rule]) -> int:
    """检查并淘汰低质量规则"""
    deprecated_count = 0
    
    for rule in rules:
        # 条件：使用 >= 5 次 且 有效率 < 30%
        if rule.use_count >= 5 and rule.effective_rate < 0.3:
            rule.is_deprecated = True
            deprecated_count += 1
            logger.info(f"规则 {rule.rule_id} 已自动淘汰（有效率 {rule.effective_rate:.1%}）")
    
    return deprecated_count
```

### 3.4 手动管理（Option 2）

#### 规则管理页面 API

| API | 方法 | 说明 |
|-----|------|------|
| `/api/rules` | GET | 获取规则列表 |
| `/api/rules/:id` | DELETE | 删除规则 |
| `/api/rules/:id` | PATCH | 编辑/禁用规则 |
| `/api/rules/cleanup` | POST | 手动触发清理（删除已淘汰规则） |

#### 规则管理页面

```html
<!-- 规则管理面板 -->
<div class="rule-manager">
  <div class="rule-stats">
    <span>总规则：{{ total }}</span>
    <span>活跃：{{ active }}</span>
    <span>已淘汰：{{ deprecated }}</span>
  </div>
  
  <div class="rule-list">
    {% for rule in rules %}
    <div class="rule-item" data-id="{{ rule.rule_id }}">
      <div class="rule-content">
        <span class="rule-type">[{{ rule.type }}]</span>
        <span class="rule-text">{{ rule.rule_text }}</span>
      </div>
      <div class="rule-meta">
        <span>使用：{{ rule.use_count }}</span>
        <span>有效率：{{ rule.effective_rate }}%</span>
        {% if rule.is_deprecated %}
        <span class="deprecated">❌ 已淘汰</span>
        {% endif %}
      </div>
      <div class="rule-actions">
        <button onclick="toggleRule('{{ rule.rule_id }}')">
          {{ '✅ 启用' if rule.is_deprecated else '❌ 禁用' }}
        </button>
        <button onclick="deleteRule('{{ rule.rule_id }}')">🗑️ 删除</button>
      </div>
    </div>
    {% endfor %}
  </div>
  
  <button onclick="cleanupDeprecated()">🧹 清理已淘汰规则</button>
</div>
```

---

## 4. 用户体验设计

### 4.1 学习反馈展示

#### 场景 1：用户给反馈后自动学习

```
┌────────────────────────────────────────────────────────┐
│  用例生成完成 ✓                                        │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 🔄 Harness 正在学习...                            │  │
│  │    提取到 2 条规则，已入库                         │  │
│  │    • 测试用例必须包含前置条件                     │  │
│  │    • 预期结果要具体可验证                         │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  [👍 好] [👎 差]  ← 用户依然可以给反馈                 │
└────────────────────────────────────────────────────────┘
```

#### 场景 2：规则被自动淘汰

```
┌────────────────────────────────────────────────────────┐
│  🔔 规则更新                                           │
│                                                        │
│  「测试用例必须有注释」已被自动禁用                     │
│  原因：使用 5 次后有效率仅 20%                         │
│                                                        │
│  [查看详情] [恢复启用] [删除]                          │
└────────────────────────────────────────────────────────┘
```

#### 场景 3：手动学习预览

```
┌────────────────────────────────────────────────────────┐
│  📚 学习规则                                            │
│                                                        │
│  将从以下 3 条标注中学习：                              │
│  • TC_001 ✅ 可投产                                    │
│  • TC_003 ❌ 舍弃（缺少边界值）                        │
│  • TC_007 ⚠️ 待修改                                    │
│                                                        │
│  预览提取的规则：                                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │ 1. [边界值] 时间范围要完整，不能只测到12:00       │  │
│  │    状态：✅ 审核通过                            │  │
│  ├──────────────────────────────────────────────────┤  │
│  │ 2. [字段格式] 预期结果要包含具体数值             │  │
│  │    状态：✅ 审核通过                            │  │
│  ├──────────────────────────────────────────────────┤  │
│  │ 3. [通用] 用例标题要清晰简洁                    │  │
│  │    状态：⚠️ 表述模糊，建议改为"标题不超过30字" │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  [确认入库] [修改后入库] [取消]                        │
└────────────────────────────────────────────────────────┘
```

### 4.2 渐进式引导

#### 首次使用提示

```
┌────────────────────────────────────────────────────────┐
│  🦆 欢迎使用 Harness 学习系统！                        │
│                                                        │
│  Harness 会从你的反馈中学习规则，让生成越来越准。      │
│                                                        │
│  使用方式：                                            │
│  1. 生成用例后，给觉得好的点 👍，不好的点 👎           │
│  2. 系统会自动学习，下次生成会应用                      │
│                                                        │
│  [知道了，不再提示] [开始使用]                         │
└────────────────────────────────────────────────────────┘
```

#### 规则库空状态

```
┌────────────────────────────────────────────────────────┐
│  🦆 Harness 还没有学习到规则                           │
│                                                        │
│  开始使用后，规则会出现在这里。                         │
│                                                        │
│  学习来源：                                            │
│  • 给用例打标签（✅❌⚠️）                             │
│  • 点击「📚 学习规则」手动触发                         │
│                                                        │
│  已有 0 条规则                                         │
└────────────────────────────────────────────────────────┘
```

---

## 5. 数据结构

### 5.1 规则扩展字段

```python
@dataclass
class Rule:
    # ... 原有字段 ...
    
    # 新增字段
    quality_score: float = 0.0      # AI 审核评分 (0-1)
    quality_reason: str = ""        # AI 审核理由
    improved_text: str = ""         # AI 改进后的文本
    auto_deprecated: bool = False   # 是否被自动淘汰
    deprecate_reason: str = ""      # 淘汰原因
```

### 5.2 规则历史记录

```python
# 新增表：规则操作日志
@dataclass
class RuleHistory:
    rule_id: str
    action: str  # "created", "used", "effective", "ineffective", "deprecated", "deleted"
    timestamp: str
    detail: str = ""
```

---

## 6. API 设计

### 6.1 自动学习 API

```python
@route("/api/rules/learn")
class RulesLearnHandler:
    """
    自动学习规则（后台调用）
    
    POST /api/rules/learn
    
    Request:
    {
        "source": "feedback" | "labeled_cases" | "manual",
        "feedbacks": [{"case_id": "TC_001", "type": "accepted", "text": "..."}],
        "cases": [{"case": {...}, "label": "accepted"}]
    }
    
    Response:
    {
        "success": true,
        "learned_count": 2,
        "discarded_count": 1,
        "rules": [{"rule_id": "RULE_003", "rule_text": "...", "quality_score": 0.9}],
        "discarded": [{"rule_text": "...", "reason": "表述不清"}]
    }
    """
```

### 6.2 规则管理 API

```python
@route("/api/rules")
class RulesHandler:
    """
    GET /api/rules
    获取规则列表（分页）
    
    Query: ?page=1&limit=20&include_deprecated=true
    
    Response:
    {
        "success": true,
        "rules": [...],
        "stats": {
            "total": 15,
            "active": 12,
            "deprecated": 3
        }
    }
    """

@route("/api/rules/:id")
class RuleDetailHandler:
    """
    PATCH /api/rules/:id
    更新规则（启用/禁用/编辑）
    
    Request:
    {
        "is_deprecated": false,        # 手动启用
        "rule_text": "修改后的文本",  # 手动编辑
        "tags": ["边界值", "高频"]     # 添加标签
    }
    
    DELETE /api/rules/:id
    删除规则
    """

@route("/api/rules/cleanup")
class RulesCleanupHandler:
    """
    POST /api/rules/cleanup
    清理已淘汰的规则（物理删除）
    
    Response:
    {
        "success": true,
        "deleted_count": 3
    }
    """
```

---

## 7. 实施计划

### Phase 1：核心功能

| 任务 | 文件 | 优先级 |
|------|------|--------|
| 扩展 Rule 数据结构 | src/harness/models.py | P0 |
| 实现 AI 自审器 | src/harness/rule_quality_checker.py | P0 |
| 修改规则提取器支持自审 | src/harness/rule_extractor.py | P0 |
| 实现自动学习 API | web/app.py | P0 |
| 前端展示学习结果 | web/templates/index.html | P0 |

### Phase 2：质量保障

| 任务 | 文件 | 优先级 |
|------|------|--------|
| 实现自动淘汰逻辑 | src/harness/memory_store.py | P1 |
| 实现手动管理 API | web/app.py | P1 |
| 前端规则管理页面 | web/templates/index.html | P1 |

### Phase 3：体验优化

| 任务 | 文件 | 优先级 |
|------|------|--------|
| 首次使用引导 | web/templates/index.html | P2 |
| 规则历史记录 | src/harness/rule_history.py | P2 |

---

## 8. 测试用例

### 8.1 自动学习测试

```python
def test_auto_learn_from_feedback():
    """用户给反馈后自动学习"""
    # 1. 生成用例
    result = generate("优惠券功能")
    
    # 2. 给反馈
    submit_feedback("TC_001", "rejected", "缺少边界值测试")
    
    # 3. 验证规则入库
    rules = memory_store.load_rules()
    assert any("边界值" in r.rule_text for r in rules)

def test_ai_quality_check_rejects_bad_rules():
    """AI 自审过滤错误规则"""
    bad_rule = "测试用例要好"
    result = quality_checker.check(bad_rule)
    assert result["approve"] == False
    assert "太模糊" in result["reason"]
```

### 8.2 自动淘汰测试

```python
def test_auto_deprecate_low_quality_rules():
    """使用5次后有效率<30%自动淘汰"""
    rule_id = memory_store.add_rule("测试规则", ...)
    
    # 模拟使用5次，4次无效
    for i in range(4):
        memory_store.record_feedback(rule_id, is_effective=False)
    memory_store.record_feedback(rule_id, is_effective=True)
    
    # 检查是否被淘汰
    rules = memory_store.load_rules()
    rule = next(r for r in rules if r.rule_id == rule_id)
    assert rule.is_deprecated == True
```

---

*文档版本：v2.0 | 最后更新：2026-04-24*
