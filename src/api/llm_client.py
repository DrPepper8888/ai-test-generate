"""
LLM HTTP 调用封装 — 纯 Python 标准库实现
支持：
  - OpenAI         https://api.openai.com
  - Anthropic      https://api.anthropic.com
  - Azure OpenAI   https://<resource>.openai.azure.com
  - Ollama         http://localhost:11434   （无需 api_key）
  - vLLM / FastChat / 任意兼容 OpenAI Chat Completions 接口的服务
"""

import json
import os
import urllib.request
import urllib.error
from typing import Optional


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


class LLMClient:
    """
    统一 LLM HTTP 客户端
    - 不依赖任何第三方库
    - api_key 优先级：config.json > 环境变量 LLM_API_KEY > 空（内网无鉴权服务）
    """

    def __init__(
        self,
        base_url: str,
        model_name: str,
        api_key: str = "",
        timeout: int = 60,
        max_tokens: int = 4000,
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
            timeout=llm.get("timeout", 60),
            max_tokens=llm.get("max_tokens", 4000),
            temperature=llm.get("temperature", 0.7),
        )

    # ── 公共接口 ────────────────────────────────────────────────────

    def chat(self, system_prompt: str, user_message: str) -> str:
        if self.provider in ("anthropic", "volcengine_coding"):
            return self._chat_anthropic(system_prompt, user_message)
        else:
            return self._chat_openai_compat(system_prompt, user_message)

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
                err_msg = json.loads(err_body).get("error", {}).get("message", err_body)
            except Exception:
                err_msg = str(e)

            if e.code == 401:
                raise RuntimeError(
                    f"鉴权失败（HTTP 401）：API Key 无效或未配置。\n"
                    f"请在 config.json 填写 api_key，或设置环境变量 LLM_API_KEY。\n"
                    f"详情：{err_msg}"
                ) from e
            elif e.code == 429:
                raise RuntimeError(f"请求频率超限（HTTP 429）：{err_msg}") from e
            else:
                raise RuntimeError(f"API 返回错误（HTTP {e.code}）：{err_msg}") from e

        except urllib.error.URLError as e:
            raise ConnectionError(
                f"无法连接到 LLM 服务（{self.base_url}）。\n"
                f"外网：检查网络和 API Key；内网：确认本地服务已启动。\n"
                f"错误：{getattr(e, 'reason', e)}"
            ) from e

        except TimeoutError:
            raise TimeoutError(
                f"请求超时（>{self.timeout}s）。可在 config.json 增大 timeout。"
            )
