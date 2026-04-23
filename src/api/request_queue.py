"""
任务队列 - 串行执行任务，避免并发调用大模型

完全使用 Python 标准库，无第三方依赖

设计理念：
1. 任务驱动：不管是谁发起的请求，统一排队
2. 串行执行：同一时间只执行一个任务
3. 状态透明：可以查看队列状态
"""

import json
import time
import uuid
import fcntl
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class Task:
    """任务"""
    task_id: str
    timestamp: str
    status: str  # waiting, processing, completed, failed
    position: int  # 队列位置（0 表示正在执行）


class TaskQueue:
    """
    任务队列管理器
    
    特点：
    1. 无需用户标识，所有请求统一排队
    2. 基于文件的锁机制，确保线程安全
    3. 简单的状态管理
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, queue_dir: Optional[Path] = None):
        if hasattr(self, '_initialized'):
            return
            
        if queue_dir is None:
            queue_dir = Path("data/queue")
        self.queue_dir = Path(queue_dir)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        
        self.queue_file = self.queue_dir / "queue.json"
        self.lock_file = self.queue_dir / ".queue.lock"
        self._initialized = True
        
        # 确保队列文件存在
        if not self.queue_file.exists():
            self._write_queue([])

    # ── 队列操作 ─────────────────────────────────────────────

    def add_task(self) -> Task:
        """
        添加新任务到队列末尾
        
        Returns:
            Task: 新建的任务
        """
        task = Task(
            task_id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            status="waiting",
            position=0,  # 临时值，后面会更新
        )
        
        self._write_queue_safe(lambda queue: queue.append(asdict(task)))
        
        # 更新位置
        return self.update_task_position(task.task_id)

    def update_task_position(self, task_id: str) -> Optional[Task]:
        """更新任务位置"""
        tasks = self._read_queue()
        for i, t in enumerate(tasks):
            if t["task_id"] == task_id:
                t["position"] = i + 1
                # 如果是队首，标记为 processing
                if i == 0:
                    t["status"] = "processing"
                break
        
        self._write_queue(tasks)
        
        # 返回更新后的任务
        for t in tasks:
            if t["task_id"] == task_id:
                return Task(**t)
        return None

    def is_my_turn(self, task_id: str) -> bool:
        """检查是否是队首任务"""
        tasks = self._read_queue()
        if not tasks:
            return False
        return tasks[0]["task_id"] == task_id

    def complete_task(self, task_id: str) -> bool:
        """完成任务，移除队列"""
        return self._write_queue_safe(lambda queue: self._remove_task(queue, task_id))

    def fail_task(self, task_id: str, error: str = "") -> bool:
        """标记任务失败"""
        def fail(queue):
            for t in queue:
                if t["task_id"] == task_id:
                    t["status"] = "failed"
                    break
            self._remove_task(queue, task_id)
            return True
        return self._write_queue_safe(fail)

    def _remove_task(self, queue: List[Dict], task_id: str) -> bool:
        """从队列移除任务"""
        original_len = len(queue)
        queue[:] = [t for t in queue if t["task_id"] != task_id]
        return len(queue) < original_len

    def get_status(self) -> Dict[str, Any]:
        """获取队列状态"""
        tasks = self._read_queue()
        
        waiting = [t for t in tasks if t["status"] == "waiting"]
        processing = [t for t in tasks if t["status"] == "processing"]
        
        return {
            "total": len(tasks),
            "processing": len(processing),
            "waiting": len(waiting),
            "has_queue": len(tasks) > 0,
            "estimated_wait_time": len(waiting) * 15,  # 每任务约15秒
        }

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取特定任务状态"""
        tasks = self._read_queue()
        
        for i, t in enumerate(tasks):
            if t["task_id"] == task_id:
                wait_time = 0
                try:
                    ts = datetime.fromisoformat(t["timestamp"])
                    wait_time = (datetime.now() - ts).total_seconds()
                except:
                    pass
                
                return {
                    "task_id": t["task_id"],
                    "status": t["status"],
                    "position": i + 1,
                    "total_waiting": len(waiting),
                    "wait_time": round(wait_time, 1),
                }
        return None

    def get_first_task(self) -> Optional[Task]:
        """获取队首任务"""
        tasks = self._read_queue()
        if not tasks:
            return None
        return Task(**tasks[0])

    # ── 锁操作 ─────────────────────────────────────────────

    def _read_queue(self) -> List[Dict]:
        """读取队列"""
        try:
            return json.loads(self.queue_file.read_text(encoding="utf-8"))
        except:
            return []

    def _write_queue(self, queue: List[Dict]):
        """写入队列"""
        self.queue_file.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _acquire_lock(self) -> bool:
        """获取锁"""
        try:
            self.lock_file.touch(exist_ok=True)
            fd = self.lock_file.open('w')
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except:
            return False

    def _release_lock(self):
        """释放锁"""
        try:
            fd = self.lock_file.open('w')
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except:
            pass

    def _write_queue_safe(self, operation) -> bool:
        """线程安全的队列操作"""
        while not self._acquire_lock():
            time.sleep(0.05)
        
        try:
            queue = self._read_queue()
            result = operation(queue)
            self._write_queue(queue)
            return result if result is not None else True
        finally:
            self._release_lock()


class TaskContext:
    """
    任务上下文管理器
    
    用法：
    with TaskContext(queue) as task:
        # 这里执行任务
        do_something()
    # 退出时自动标记完成
    """

    def __init__(self, queue: TaskQueue, timeout: int = 300):
        self.queue = queue
        self.task: Optional[Task] = None
        self.timeout = timeout
        self.start_time = None

    def __enter__(self) -> Task:
        # 添加任务
        self.task = self.queue.add_task()
        self.start_time = time.time()
        
        # 等待轮到
        while True:
            if self.queue.is_my_turn(self.task.task_id):
                # 标记为处理中
                self.task = self.queue.update_task_position(self.task.task_id)
                if self.task and self.task.status == "processing":
                    break
            if time.time() - self.start_time > self.timeout:
                raise TimeoutError("等待队列超时")
            time.sleep(0.5)
        
        return self.task

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.task:
            if exc_type is not None:
                # 执行失败
                self.queue.fail_task(self.task.task_id, str(exc_val)[:100])
            else:
                # 执行成功
                self.queue.complete_task(self.task.task_id)
        return False  # 不吞掉异常
