#!/usr/bin/env python3
"""
团队规则合并脚本（管理员用）
用法：
1. 把大家导出的 *.json 规则文件都放到 team-rules/ 文件夹
2. 运行：python3 merge_team_rules.py
3. 生成的 merged-team-rules.json 发给所有人导入
"""
import json
from pathlib import Path
from collections import defaultdict

TEAM_RULES_FOLDER = Path("team-rules")
OUTPUT_FILE = Path("merged-team-rules.json")


def merge_rules():
    if not TEAM_RULES_FOLDER.exists():
        TEAM_RULES_FOLDER.mkdir()
        print(f"📂 创建文件夹：{TEAM_RULES_FOLDER}")
        print("请把大家导出的规则 JSON 文件放到这个文件夹里，再重新运行")
        return

    rule_files = list(TEAM_RULES_FOLDER.glob("*.json"))
    if not rule_files:
        print(f"❌ {TEAM_RULES_FOLDER} 文件夹里没有找到 JSON 文件")
        return

    print(f"\n📦 找到 {len(rule_files)} 份规则文件：")
    for f in rule_files:
        print(f"  - {f.name}")

    # 收集所有规则
    all_rule_lists = []
    for f in rule_files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # 兼容直接导出的数组和带包装的格式
            if isinstance(data, list):
                all_rule_lists.append(data)
            elif isinstance(data, dict) and "rules" in data:
                all_rule_lists.append(data["rules"])
            else:
                print(f"⚠️  {f.name} 格式不对，跳过")
        except Exception as e:
            print(f"⚠️  读取 {f.name} 失败：{e}")

    if not all_rule_lists:
        print("❌ 没有可合并的规则")
        return

    print(f"\n🔄 正在合并 {len(all_rule_lists)} 份规则...")

    # 按规则文本聚合
    merged_map = defaultdict(lambda: {
        "use_count": 0,
        "effective_count": 0,
        "source_count": 0,
        "types": set(),
        "max_level": "",
    })

    for rule_list in all_rule_lists:
        for r in rule_list:
            if "rule_text" not in r:
                continue
            rt = r["rule_text"]
            merged_map[rt]["use_count"] += r.get("use_count", 1)
            merged_map[rt]["effective_count"] += r.get("effective_count", 0)
            merged_map[rt]["source_count"] += 1
            merged_map[rt]["original_rule"] = r  # 保留第一条的其他字段

    # 转成列表
    merged_rules = []
    for i, (rule_text, stats) in enumerate(merged_map.items()):
        original = stats["original_rule"]
        merged_rules.append({
            "rule_id": f"RULE_{i+1:04d}",
            "rule_text": rule_text,
            "type": original.get("type", "general"),
            "level": "global" if stats["source_count"] >= 3 else original.get("level", "global"),
            "created_at": original.get("created_at", ""),
            "use_count": stats["use_count"],
            "effective_count": stats["effective_count"],
            "source_count": stats["source_count"],  # 多少人贡献了这条
            "is_deprecated": original.get("is_deprecated", False),
        })

    # 按使用量排序，用的人越多越靠前
    merged_rules.sort(key=lambda x: (-x["source_count"], -x["use_count"]))

    # 保存
    OUTPUT_FILE.write_text(
        json.dumps(merged_rules, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 统计
    high_quality = len([r for r in merged_rules if r["source_count"] >= 3])
    total_use_count = sum(r["use_count"] for r in merged_rules)

    print("\n" + "=" * 50)
    print("✅ 合并完成！")
    print("=" * 50)
    print(f"  合并前总规则数：{sum(len(r) for r in all_rule_lists)}")
    print(f"  合并后总规则数：{len(merged_rules)}")
    print(f"  团队共识规则（≥3人用）：{high_quality} 条")
    print(f"  总使用次数：{total_use_count}")
    print(f"\n  输出文件：{OUTPUT_FILE}")
    print("\n💡 建议：把 merged-team-rules.json 发群里，大家导入就能用上全团队的智慧了！")


if __name__ == "__main__":
    merge_rules()
