"""
队列化 LLM 客户端 - 任务驱动串行执行

完全使用 Python 标准库，无第三方依赖

设计理念：
1. 任务驱动：每个请求自动入队，无需用户标识
2. 串行执行：同一时间只调用一次 LLM
3. 自动管理：请求完成后自动释放队列
"""

import json
import time
from pathlib import Path
from typing import Optional

from src.api.llm_client import LLMClient
from src.api.request_queue import TaskQueue, TaskContext


class QueuedLLMClient:
    """
    队列化 LLM 客户端
    
    特点：
    1. 任务驱动：每个 chat() 调用自动排队
    2. 单例模式：全局共享同一个队列
    3. 自动管理：上下文管理器自动处理队列
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: dict = None):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        if config is None:
            config = {}
        
        llm_cfg = config.get("llm", {})
        self.client = LLMClient(
            base_url=llm_cfg.get("base_url", "http://localhost:11434"),
            model_name=llm_cfg.get("model_name", "qwen2.5:7b"),
            api_key=llm_cfg.get("api_key", ""),
            timeout=llm_cfg.get("timeout", 120),
            max_tokens=llm_cfg.get("max_tokens", 4096),
            temperature=llm_cfg.get("temperature", 0.7),
        )
        
        self.queue = TaskQueue()
        self._initialized = True

    @classmethod
    def from_config(cls, config: dict) -> "QueuedLLMClient":
        """从配置创建实例"""
        return cls(config)

    def chat(self, system_prompt: str, user_message: str, timeout: int = 300) -> str:
        """
        排队调用 chat
        
        Args:
            system_prompt: 系统提示词
            user_message: 用户消息
            timeout: 等待队列超时时间（秒）
            
        Returns:
            LLM 响应
        """
        with TaskContext(self.queue, timeout) as task:
            return self.client.chat(system_prompt, user_message)

    def health_check(self) -> dict:
        """健康检查（不排队）"""
        return self.client.health_check()

    @classmethod
    def get_queue_status(cls) -> dict:
        """获取队列状态"""
        queue = TaskQueue()
        return queue.get_status()

    @classmethod
    def check_task_status(cls, task_id: str) -> Optional[dict]:
        """检查任务状态"""
        queue = TaskQueue()
        return queue.get_task_status(task_id)
