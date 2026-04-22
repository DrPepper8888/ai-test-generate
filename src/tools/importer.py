"""
文件导入器 — 解析 CSV / JSON 文件为用例
仅使用 Python 原生包，无第三方依赖
支持 .csv 和 .json 格式
"""
import csv
import json
from pathlib import Path
from typing import Optional, List, Dict


def parse_csv(file_path: str, encoding: str = "utf-8") -> List[Dict]:
    """解析 CSV 文件（Python 原生 csv 模块）"""
    cases = []
    with open(file_path, "r", encoding=encoding, newline="", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cases.append({k: v for k, v in row.items() if v})
    return cases


def parse_json(file_path: str) -> List[Dict]:
    """解析 JSON 文件（Python 原生 json 模块）"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict) and "cases" in data:
            return data["cases"]
        if isinstance(data, list):
            return data
        raise ValueError("JSON 文件格式错误，需要是数组或包含 cases 字段的对象")


def detect_encoding(file_path: str) -> str:
    """自动检测文件编码"""
    encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.read(1024)
            return enc
        except UnicodeDecodeError:
            continue
    return "utf-8"


def import_file_to_cases(file_path: str) -> List[Dict]:
    """
    导入文件并返回用例列表

    Args:
        file_path: 文件路径

    Returns:
        用例列表
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        enc = detect_encoding(file_path)
        return parse_csv(file_path, enc)
    elif suffix == ".json":
        return parse_json(file_path)
    else:
        raise ValueError(f"不支持的文件格式：{suffix}，仅支持 .csv, .json")
