# AI 测试用例生成器

> 借鉴 OpenClaw 的设计理念：从用户交互中学习，越用越准

---

## 项目状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| P0 | ✅ 已完成 | 最小可用版本 |
| P1 | ✅ 已完成 | 质量优化 |
| P2 | 🚧 进行中 | 记忆与学习系统 |

---

## 快速启动

### 安装依赖

**无需安装任何第三方包！**

### 配置 LLM

编辑 `config.json`：
```json
{
  "llm": {
    "base_url": "https://ark.cn-beijing.volces.com/api/coding",
    "model_name": "deepseek-v3.2",
    "api_key": "ark-xxxxxx"
  }
}
```

### 启动服务

```bash
python web/app.py
```

访问：http://localhost:5000

---

## 目录结构

```
ai-test-case-generator/
├── README.md                  # 本文档
├── P1开发文档.md              # P1 开发详细文档
├── config.json              # LLM 配置
├── AGENTS.md                # 踩坑记录
├── AI测试用例生成器-项目规格说明书.docx  # 完整项目规格
├── prompts/                 # 提示词
│   ├── system_prompt.md       # 生成用例提示词
│   └── review_prompt.md       # 评审提示词
├── web/                     # Web 服务
│   └── app.py                # http.server 入口
├── src/                     # 核心代码
│   ├── api/
│   │   └── llm_client.py     # LLM HTTP 客户端
│   ├── workflow/
│   │   └── pipeline.py       # 状态机编排
│   ├── tools/
│   │   ├── formatter.py      # 格式校验
│   │   ├── exporter.py       # Markdown/CSV 导出
│   │   ├── importer.py       # Excel/CSV 导入
│   │   └── deduplicator.py   # 去重（相似度>0.98）
│   └── memory/              # 记忆与学习系统（P2）
│       ├── memory_store.py    # Memory 存储
│       ├── rule_extractor.py  # 规则提取
│       └── rule_injector.py   # 规则注入
└── data/                    # 数据目录
    ├── history.json           # 生成历史
    ├── feedback.json          # 用户反馈
    └── memory/               # 记忆系统数据（P2）
        ├── interactions/      # 交互历史
        ├── rules.json         # 学习到的规则
        └── annotated_cases.json  # 标注用例库
```

---

## P1 功能清单

| 功能 | 说明 |
|------|------|
| 双 Agent 评审 | `review_mode=True` 开启二次 LLM 评审 |
| 简单去重 | `difflib` 相似度 > 0.98 自动去重 |
| Token 控制 | 自动分批，避免 token 超限 |
| 用户反馈 | rating + type + comment |
| 历史查询 | `/api/history` 接口 |
| 文件导入 | Excel/CSV 上传 |
| 文件导出 | Markdown/CSV 下载 |

---

## P2 设计理念

### 记忆系统

```
用户反馈
  ↓
存入 interactions/
  ↓
RuleExtractor 总结规则
  ↓
存入 rules.json
  ↓
RuleInjector 注入到 system prompt
  ↓
下次生成自动更准
```

### rules.json 示例

```json
[
  {
    "rule_id": "RULE_001",
    "type": "field_value",
    "rule_text": "前置条件必须包含用户登录状态",
    "source": "用户反馈 2025-xx-xx",
    "use_count": 5
  }
]
```

---

## 开发规范

- 使用 Python 标准库，减少第三方依赖
- 类型提示使用 `typing`
- 私有方法以 `_` 开头
- 错误信息返回给前端展示

---

## 常见问题

### 如何切换 LLM？
修改 `config.json` 中的 `base_url` 和 `model_name`。

### 如何开启评审？
调用 API 时设置 `review_mode: true`。

### 去重阈值是多少？
固定 0.98（相似度超过 98% 去重）。

### 支持哪些文件格式？
导入：.xlsx, .xls, .csv（需要 openpyxl）
导出：Markdown, .csv

---

*最后更新：P2 进行中*
