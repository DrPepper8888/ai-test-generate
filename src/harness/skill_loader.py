"""
自定义规则加载器 - 加载用户编写的 skill.md

完全使用 Python 标准库，无第三方依赖
"""

import re
from pathlib import Path
from typing import Optional, List


class SkillLoader:
    """自定义规则加载器"""

    # 注释标记（这些行不会被注入）
    COMMENT_PREFIXES = ["# ", "<!--", "// ", "/*"]

    # 分隔符（分隔元信息和规则内容）
    SEPARATOR = "---"

    def __init__(self, skill_path: Optional[Path] = None):
        """
        初始化加载器
        
        Args:
            skill_path: skill.md 文件路径，默认使用 prompts/skill.md
        """
        if skill_path is None:
            self.skill_path = Path("prompts/skill.md")
        else:
            self.skill_path = Path(skill_path)

    def load(self) -> Optional[str]:
        """
        加载并解析 skill.md
        
        Returns:
            解析后的规则文本，如果文件不存在返回 None
        """
        if not self.skill_path.exists():
            return None

        try:
            content = self.skill_path.read_text(encoding="utf-8")
            return self._parse(content)
        except (OSError, UnicodeDecodeError):
            return None

    def _parse(self, content: str) -> str:
        """
        解析 skill.md 内容
        
        处理逻辑：
        1. 移除以 # 开头的注释行
        2. 保留 Markdown 代码块内容（规则示例）
        3. 合并连续的空行
        
        Args:
            content: 原始内容
            
        Returns:
            解析后的规则文本
        """
        lines = content.split("\n")
        result_lines = []
        skip_next = 0  # 跳过后续 N 行（用于代码块）

        for i, line in enumerate(lines):
            # 跳过代码块内容
            if skip_next > 0:
                skip_next -= 1
                # 保留代码块内容，但移除 ``` 标记
                if line.strip().startswith("```"):
                    continue
                result_lines.append(line)
                continue

            # 检测代码块开始
            if line.strip().startswith("```"):
                skip_next = 0  # 不跳过后续内容
                result_lines.append(line)  # 保留代码块边界
                continue

            # 移除注释行
            stripped = line.strip()
            if any(stripped.startswith(prefix) for prefix in self.COMMENT_PREFIXES):
                continue

            # 移除 Markdown 链接和图片（保留文本）
            line = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)

            # 保留非空行
            if stripped:
                result_lines.append(line)

        # 合并结果
        result = "\n".join(result_lines)

        # 如果结果只包含代码块，提取代码块内容
        if result.strip().startswith("```"):
            # 简单处理：移除前后代码块标记
            result = re.sub(r'^```\w*\n', '', result)
            result = re.sub(r'\n```$', '', result)

        return result.strip()

    def get_inject_text(self) -> str:
        """
        获取注入到 prompt 的文本
        
        Returns:
            格式化的注入文本
        """
        rules = self.load()
        if not rules:
            return ""

        return f"""
---
【自定义规则】（来自 skill.md）
{rules}
---
"""

    @staticmethod
    def get_default_template() -> str:
        """
        获取默认模板
        
        Returns:
            默认的 skill.md 模板内容
        """
        return """# 测试规则模板

你可以在这里定义项目专属的测试用例编写规则。

## 使用方式

1. 编辑本文件，添加你的规则
2. 保存后，AI 生成时会自动遵守这些规则

## 示例规则格式

```markdown
# 测试用例必须包含的字段
1. ID：用例编号（格式：TC_XXX）
2. 标题：用例名称
3. 前置条件：必要的初始状态
4. 测试步骤：清晰的执行步骤
5. 预期结果：明确的可验证结果
6. 优先级：P0/P1/P2

# 命名规范
- P0：核心功能，阻塞性缺陷
- P1：重要功能，非阻塞性缺陷
- P2：边缘场景
```

## 提示

- 使用 Markdown 格式
- 以 `#` 开头的行是注释
- 代码块内的内容会被保留作为规则示例
"""
