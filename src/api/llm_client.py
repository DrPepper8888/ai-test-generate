# -*- coding: utf-8 -*-
"""
LLM HTTP 调用封装 — 纯 Python 标准库实现
支持：
  - OpenAI         https://api.openai.com
  - Anthropic      https://api.anthropic.com
  - 火山方舟        https://ark.cn-beijing.volces.com/api/coding
  - Ollama         http://localhost:11434   （无需 api_key）
  - vLLM / FastChat / 任意兼容 OpenAI Chat Completions 接口的服务

特性：
  - 自动过滤模型思考过程（<think>...</think>）
  - 可配置 max_tokens 避免截断或浪费
"""

import json
import os
import re
import urllib.request
import urllib.error
from typing import Optional
from dataclasses import dataclass


@dataclass
class LLMError(Exception):
    """LLM 调用错误"""
    error_type: str = "UNKNOWN"
    message: str = ""
    details: str = ""
    suggestion: str = ""
    
    def __str__(self):
        parts = [self.message]
        if self.details:
            parts.append(f"详情：{self.details}")
        if self.suggestion:
            parts.append(f"建议：{self.suggestion}")
        return "\n".join(parts)
    
    def to_dict(self):
        return {
            "error_type": self.error_type,
            "message": self.message,
            "details": self.details,
            "suggestion": self.suggestion
        }


# ── 供应商路由规则 ─────────────────────────────────────────────────
def _detect_provider(base_url: str) -> str:
    """根据 base_url 推断供应商类型"""
    url = base_url.lower().rstrip("/")
    if "anthropic.com" in url:
        return "anthropic"
    if "azure.com" in url:
        return "azure"
    if "ark.cn-beijing.volces.com/api/coding" in url:
        return "volcengine_coding"
    return "openai_compat"


# ── 思考过程过滤 ──────────────────────────────────────────────────
THINKING_PATTERNS = [
    # DeepSeek 风格
    (r"<think>[\s\S]*?</think>", ""),
    # Anthropic 风格
    (r"<think>[\s\S]*?</think>", ""),
    # 通用的 XML 标签风格
    (r"<thinking>[\s\S]*?</thinking>", ""),
    (r"<reasoning>[\s\S]*?</reasoning>", ""),
    # Markdown 代码块包裹的思考
    (r"```thinking[\s\S]*?```", ""),
    (r"```think[\s\S]*?```", ""),
]


def strip_thinking_content(text: str) -> str:
    """
    过滤掉模型思考过程内容
    
    支持的格式：
    - <think>...</think>
    - <think>...</think>
    - <thinking>...</thinking>
    - <reasoning>...</reasoning>
    
    Args:
        text: 模型原始输出
        
    Returns:
        过滤后的文本
    """
    if not text:
        return text
    
    result = text
    for pattern, replacement in THINKING_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    
    # 清理多余空行
    result = re.sub(r"\n{3,}", "\n\n", result)
    
    return result.strip()


class LLMClient:
    """
    统一 LLM HTTP 客户端
    - 不依赖任何第三方库
    - 自动过滤思考过程
    - api_key 优先级：config.json > 环境变量 LLM_API_KEY > 空（内网无鉴权服务）
    """

    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str = "",
        timeout: int = 120,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.provider = _detect_provider(base_url)
        # api_key 优先级：参数 > 环境变量
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")

    @classmethod
    def from_config(cls, config: dict) -> "LLMClient":
        llm = config.get("llm", {})
        return cls(
            base_url=llm.get("base_url", "http://localhost:11434"),
            model_name=llm.get("model_name", "qwen2.5:7b"),
            api_key=llm.get("api_key", ""),
            timeout=llm.get("timeout", 120),
            max_tokens=llm.get("max_tokens", 4096),
            temperature=llm.get("temperature", 0.7),
        )

    # ── 公共接口 ────────────────────────────────────────────────────

    def chat(self, system_prompt: str, user_message: str) -> str:
        if self.provider in ("anthropic", "volcengine_coding"):
            raw = self._chat_anthropic(system_prompt, user_message)
        else:
            raw = self._chat_openai_compat(system_prompt, user_message)
        
        # 检查 LLM 返回是否为空
        if not raw or not isinstance(raw, str):
            raise RuntimeError("LLM 返回内容为空，可能是 API 调用失败或模型输出被截断")
        
        # 过滤思考过程
        result = strip_thinking_content(raw)
        
        # 过滤后检查是否为空
        if not result:
            # 检查是否是本地模型限制
            is_local = any(x in self.base_url for x in ['localhost', '127.0.0.1', 'ollama'])
            if is_local:
                raise LLMError(
                    error_type="LOCAL_MODEL_LIMIT",
                    message="本地模型输出被截断",
                    details="输出内容过长，触发了本地模型的截断限制",
                    suggestion="建议：1) 减少生成数量（5-7条）；2) 简化需求描述；3) 使用云端模型获得更好效果"
                )
            raise RuntimeError(f"LLM 返回内容在移除思考过程后为空。原始内容：{raw[:200]}...")
        
        return result

    def health_check(self) -> dict:
        try:
            result = self.chat("你是一个助手。", "请只回复数字1，不要有其他内容。")
            return {
                "status": "ok",
                "provider": self.provider,
                "model": self.model_name,
                "response_preview": result[:60],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── OpenAI 兼容接口（Ollama / vLLM / OpenAI / Azure） ──────────

    def _chat_openai_compat(self, system_prompt: str, user_message: str) -> str:
        if self.provider == "azure":
            endpoint = (
                f"{self.base_url}/openai/deployments/{self.model_name}"
                f"/chat/completions?api-version=2024-02-01"
            )
        else:
            endpoint = f"{self.base_url}/v1/chat/completions"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.api_key:
            if self.provider == "azure":
                headers["api-key"] = self.api_key
            else:
                headers["Authorization"] = f"Bearer {self.api_key}"
        # 无 api_key → 内网无鉴权 Ollama/vLLM，不加 Authorization

        data = self._do_request(endpoint, payload, headers)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"解析 OpenAI 响应失败：{e}\n原始：{data}") from e

    # ── Anthropic Messages API ──────────────────────────────────────

    def _chat_anthropic(self, system_prompt: str, user_message: str) -> str:
        if self.provider == "volcengine_coding":
            endpoint = f"{self.base_url}/v1/messages"
        else:
            endpoint = f"{self.base_url}/v1/messages"
        payload = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            if self.provider == "volcengine_coding":
                headers["Authorization"] = f"Bearer {self.api_key}"
            else:
                headers["x-api-key"] = self.api_key

        data = self._do_request(endpoint, payload, headers)
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"解析 Anthropic 响应失败：{e}\n原始：{data}") from e

    # ── 底层 HTTP ────────────────────────────────────────────────────

    def _do_request(self, endpoint: str, payload: dict, headers: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
                try:
                    err_data = json.loads(err_body)
                    err_msg = err_data.get("error", {}).get("message", err_body)
                except:
                    err_msg = err_body
            except Exception:
                err_msg = str(e)

            if e.code == 401:
                raise LLMError(
                    error_type="AUTH_ERROR",
                    message="鉴权失败（HTTP 401）",
                    details=f"API Key 无效或未配置",
                    suggestion="在 config.json 填写 api_key，或设置环境变量 LLM_API_KEY"
                ) from e
            elif e.code == 403:
                raise LLMError(
                    error_type="FORBIDDEN",
                    message="访问被拒绝（HTTP 403）",
                    details=err_msg,
                    suggestion="检查 API 权限设置，确认模型是否可用"
                ) from e
            elif e.code == 404:
                raise LLMError(
                    error_type="NOT_FOUND",
                    message="资源不存在（HTTP 404）",
                    details=f"API 地址或模型名称可能错误：{self.model_name}",
                    suggestion="检查 config.json 中的 base_url 和 model_name"
                ) from e
            elif e.code == 429:
                raise LLMError(
                    error_type="RATE_LIMIT",
                    message="请求频率超限（HTTP 429）",
                    details=err_msg,
                    suggestion="稍后再试，或降低请求频率"
                ) from e
            elif e.code == 500:
                raise LLMError(
                    error_type="SERVER_ERROR",
                    message="AI 服务端错误（HTTP 500）",
                    details="AI 服务端内部错误",
                    suggestion="稍后再试，可能是服务器临时故障"
                ) from e
            elif e.code in (502, 503):
                raise LLMError(
                    error_type="SERVICE_UNAVAILABLE",
                    message=f"AI 服务暂时不可用（HTTP {e.code}）",
                    details="服务可能正在维护或过载",
                    suggestion="稍后再试"
                ) from e
            else:
                raise LLMError(
                    error_type="HTTP_ERROR",
                    message=f"API 返回错误（HTTP {e.code}）",
                    details=err_msg,
                    suggestion="检查 API 配置是否正确"
                ) from e

        except urllib.error.URLError as e:
            raise LLMError(
                error_type="NETWORK_ERROR",
                message="网络连接失败",
                details=str(e),
                suggestion=f"请检查 API 地址：{self.base_url}，确认网络是否正常"
            ) from e

        except TimeoutError:
            is_local = any(x in self.base_url for x in ['localhost', '127.0.0.1', 'ollama'])
            if is_local:
                raise LLMError(
                    error_type="LOCAL_MODEL_SLOW",
                    message="本地模型响应超时",
                    details=f"连接 {self.base_url} 超过 {self.timeout} 秒",
                    suggestion="本地模型性能有限，建议：1) 减少生成数量到 5 条；2) 简化需求描述；3) 耐心等待；4) 考虑使用云端模型"
                )
            raise LLMError(
                error_type="TIMEOUT",
                message="请求超时",
                details=f"连接 {self.base_url} 超时（{self.timeout}秒）",
                suggestion="检查网络连接，或尝试增加 config.json 中的 timeout 配置"
            ) from e
