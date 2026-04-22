# AGENTS.md — 踩坑记录与运维规则

> 本文件记录开发与部署过程中遇到的问题、决策依据及运维注意事项。

---

## 架构决策记录

### 为什么用 urllib 而不是 requests？
内网环境部署，减少第三方依赖风险。Python 标准库 urllib 完全满足
OpenAI / Anthropic 兼容接口的 HTTP POST 需求，requests 需要额外安装。

### 为什么用 Flask 而不是 FastAPI？
Flask 在内网 pip 离线安装更简单（依赖少），P0 不需要异步。

### API Key 设计
- api_key 优先级：`config.json` > 环境变量 `LLM_API_KEY` > 空
- 内网无鉴权服务（Ollama/vLLM 裸部署）：留空即可，不会加 Authorization 头
- 生产环境建议用环境变量，避免 key 写入文件被误提交

### 供应商路由
根据 base_url 自动推断，无需手动配置：
- `anthropic.com` → Anthropic Messages API（x-api-key 头）
- `azure.com`     → Azure OpenAI API（api-key 头 + deployment 路径）
- 其余            → OpenAI Chat Completions 兼容（Authorization: Bearer）

---

## 快速启动指南

### 外网验证（云端 LLM）

**方式 A：直接改 config.json**
```json
{
  "llm": {
    "base_url": "https://api.openai.com",
    "model_name": "gpt-4o-mini",
    "api_key": "sk-xxxx"
  }
}
```

**方式 B：环境变量（推荐，避免 key 写入文件）**
```bash
export LLM_API_KEY="sk-xxxx"
python web/app.py
```

**方式 C：Web 界面实时修改**
启动后点击右上角 `⚙ LLM 配置`，填写 Base URL / Model / Key，点击保存即生效。

### Anthropic Claude
```json
{ "base_url": "https://api.anthropic.com", "model_name": "claude-haiku-4-5-20251001", "api_key": "sk-ant-xxxx" }
```

### 内网 Ollama（无需 Key）
```json
{ "base_url": "http://your-intranet-server:11434", "model_name": "qwen2.5:7b", "api_key": "" }
```

### 内网 vLLM（有 Key 的自部署服务）
```json
{ "base_url": "http://your-intranet-llm:8000", "model_name": "Qwen/Qwen2.5-7B-Instruct", "api_key": "your-internal-key" }
```

### Azure OpenAI
```json
{ "base_url": "https://your-resource.openai.azure.com", "model_name": "gpt-4o-mini", "api_key": "your-azure-key" }
```

---

## 已知问题与解决方案

### Ollama 返回 SSE 流式响应导致解析失败
**解决**：请求 body 中显式设置 `"stream": false`（已内置）

### LLM 输出 Markdown 代码块包裹 JSON
**解决**：`formatter.py` 三级策略：直接解析 → 剥离代码围栏 → 提取 `[...]` 区间

### 中文字段名不一致导致校验失败
**解决**：只校验字段数量，不校验字段名拼写

### 生成数量超 20 条时 token 超限
**解决**：`pipeline.py` 自动按 `batch_size` 分批，结果合并返回

### HTTP 401 鉴权失败
检查 config.json 的 api_key 是否正确；或确认环境变量 `LLM_API_KEY` 已设置

### 内网机器无法访问外网字体
`index.html` 引用了 Google Fonts CDN（JetBrains Mono / Noto Sans SC）。
内网部署时若字体加载失败，界面会回退到系统字体，功能不受影响。
如需完全内网化，可删除 `<link>` 标签或替换为本地字体文件。

---

## P0 → P1 升级注意事项
- 双 Agent 评审在 `pipeline.py` 中预留了 `review_mode` 开关
- 去重使用 `difflib`（标准库），无需安装
- 分批逻辑已实现，P1 重点调优 batch_size

*最后更新：初始化 + API Key 支持*
