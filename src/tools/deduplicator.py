"""
去重工具 — 基于字符串相似度（优化版）
使用 Python 标准库 difflib + 语义归一化预处理
支持动态阈值 + 停用词过滤
"""
import difflib
import re
from typing import List, Dict


# 停用词表 — 测试用例描述中常见的无意义词
STOP_WORDS = {
    "进行", "操作", "的", "了", "和", "或", "与", "是", "在", "对", "将",
    "然后", "接着", "之后", "之前", "用户", "系统", "功能", "按钮", "页面",
    "输入", "点击", "选择", "提交", "确认", "取消", "返回", "查看", "编辑",
    "正常", "正确", "有效", "无效", "成功", "失败", "错误", "异常"
}


def normalize_text(text: str) -> str:
    """语义归一化预处理：
    1. 转小写
    2. 去掉标点符号
    3. 去掉停用词
    4. 去掉多余空格
    """
    text = str(text).lower().strip()
    if not text:
        return ""

    # 去掉标点和特殊字符
    text = re.sub(r'[^\w\s]', ' ', text)

    # 分词并过滤停用词
    words = text.split()
    words = [w for w in words if w and w not in STOP_WORDS]

    return ' '.join(words)


def similarity(a: str, b: str, normalize: bool = True) -> float:
    """计算两个字符串的相似度
    Args:
        normalize: 是否进行语义归一化预处理
    """
    if normalize:
        a = normalize_text(a)
        b = normalize_text(b)

    if not a or not b:
        return 0.0

    return difflib.SequenceMatcher(None, a, b).ratio()


def case_to_str(case: Dict) -> str:
    """将用例 dict 转换为可比较的字符串（只比较关键字段）"""
    # 优先比较标题和步骤，这两个字段最能区分用例
    key_fields = []
    for key in case:
        key_lower = key.lower()
        if "title" in key_lower or "标题" in key or "名称" in key:
            key_fields.append(str(case.get(key, "")))
        elif "step" in key_lower or "步骤" in key or "操作" in key:
            key_fields.append(str(case.get(key, "")))

    if key_fields:
        return " | ".join(key_fields)

    # 找不到关键字段就用全部字段
    return " | ".join(f"{v}" for v in case.values())


def get_threshold_by_scenario(scenario_type: str = "general") -> float:
    """根据场景类型动态调整去重阈值
    Args:
        scenario_type: normal/boundary/attack/business/general
    """
    thresholds = {
        "normal": 0.80,      # 正常场景更容易重复，阈值低一点
        "boundary": 0.85,    # 边界值
        "attack": 0.90,      # 攻击/异常场景，阈值高一点
        "business": 0.85,    # 业务场景
        "general": 0.85      # 默认
    }
    return thresholds.get(scenario_type, 0.85)


def deduplicate(cases: List[Dict], threshold: float = None, scenario_type: str = "general") -> List[Dict]:
    """去重：去除与已有用例相似度 > threshold 的用例
    Args:
        threshold: 相似度阈值，不传则根据场景自动选择
        scenario_type: 场景类型，用于动态选择阈值
    """
    if not cases:
        return cases

    if threshold is None:
        threshold = get_threshold_by_scenario(scenario_type)

    result = []
    for case in cases:
        case_str = case_to_str(case)
        is_duplicate = False
        for existing in result:
            if similarity(case_str, case_to_str(existing)) > threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            result.append(case)

    return result


def find_duplicates(cases: List[Dict], threshold: float = 0.85) -> List[tuple]:
    """找出相似的用例对"""
    results = []
    for i in range(len(cases)):
        for j in range(i + 1, len(cases)):
            sim = similarity(case_to_str(cases[i]), case_to_str(cases[j]))
            if sim > threshold:
                results.append((cases[i], cases[j], sim))
    return results