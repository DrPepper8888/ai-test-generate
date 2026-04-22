"""
简单去重工具 — 基于字符串相似度
使用 Python 标准库 difflib
阈值 > 0.98 则去重
"""
import difflib
from typing import List, Dict


def similarity(a: str, b: str) -> float:
    """计算两个字符串的相似度"""
    a = str(a).lower().strip()
    b = str(b).lower().strip()
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def case_to_str(case: Dict) -> str:
    """将用例 dict 转换为可比较的字符串"""
    return " | ".join(f"{k}={v}" for k, v in case.items())


def deduplicate(cases: List[Dict], threshold: float = 0.98) -> List[Dict]:
    """去重：去除与已有用例相似度 > threshold 的用例"""
    if not cases:
        return cases

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


def find_duplicates(cases: List[Dict], threshold: float = 0.98) -> List[tuple]:
    """找出相似的用例对"""
    results = []
    for i in range(len(cases)):
        for j in range(i + 1, len(cases)):
            sim = similarity(case_to_str(cases[i]), case_to_str(cases[j]))
            if sim > threshold:
                results.append((cases[i], cases[j], sim))
    return results