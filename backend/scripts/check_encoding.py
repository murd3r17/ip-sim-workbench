"""编码规范校验（A-12）：.ps1 必须带 UTF-8 BOM，其余文本文件必须不带 BOM。

背景：PowerShell 5.1 按系统代码页解码无 BOM 的 .ps1，含中文/制表符注释的脚本会
直接**解析失败**（P0-01 就是这么坏的）；反过来，BOM 混进 .md/语料会让知识库检索
把 `\\ufeff` 当成正文首字符。此脚本把规则固化下来，CI 与本地都能跑。

用法：
    python scripts/check_encoding.py            # 只检查，有问题退出码 1
    python scripts/check_encoding.py --fix      # 就地修正
    python scripts/check_encoding.py --root ..  # 检查额外目录（如语料仓库）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BOM = b"\xef\xbb\xbf"

# 需要 BOM 的后缀
BOM_REQUIRED = {".ps1", ".psm1", ".psd1"}
# 必须没有 BOM 的文本后缀
NO_BOM = {
    ".md", ".py", ".ts", ".tsx", ".vue", ".js", ".mjs", ".cjs", ".json",
    ".yml", ".yaml", ".txt", ".cfg", ".ini", ".toml", ".example", ".sh",
    ".css", ".html", ".sql", ".gitattributes", ".gitignore", ".env",
}
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".runtime",
    "third_party", "dist", "build", ".mypy_cache", ".pytest_cache",
    "playwright-report", "test-results", ".claude", "vendor-cache", "private", ".private",
}


def iter_files(root: Path):
    """遍历显式指定的根目录，只剪掉**下层**垃圾目录。

    以前用 ``root.rglob("*")`` 再按路径分段过滤，会让「显式 --root 本身位于
    ``.runtime`` 内」的情况（隔离测试的 pytest basetemp 就是如此）整个被跳过，
    于是对着一棵树报告"干净"。显式指定的根必须被检查，剪枝只作用于它的子目录。
    """
    for current, dirs, names in os.walk(root, followlinks=False):
        folder = Path(current)
        dirs[:] = sorted(d for d in dirs
                         if d not in SKIP_DIRS and not (folder / d).is_symlink())
        for name in sorted(names):
            if name == '.env' or (name.startswith('.env.') and not name.endswith(('.example', '.sample'))):
                continue
            path = folder / name
            if path.is_file() and not path.is_symlink():
                yield path


def check_tree(root: Path, fix: bool) -> list[str]:
    problems: list[str] = []
    for path in iter_files(root):
        name = path.name
        suffix = path.suffix.lower()
        if suffix not in BOM_REQUIRED and suffix not in NO_BOM and name not in NO_BOM:
            continue
        data = path.read_bytes()
        has_bom = data.startswith(BOM)
        rel = path.relative_to(root)
        if suffix in BOM_REQUIRED and not has_bom:
            if fix:
                path.write_bytes(BOM + data)
                problems.append(f"[已修] 补 BOM: {rel}")
            else:
                problems.append(f"缺少 BOM: {rel}")
        elif suffix in NO_BOM and has_bom:
            if fix:
                path.write_bytes(data[len(BOM):])
                problems.append(f"[已修] 去 BOM: {rel}")
            else:
                problems.append(f"多余 BOM: {rel}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 .ps1 带 BOM、其它文本不带 BOM")
    parser.add_argument("--fix", action="store_true", help="就地修正")
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help="要检查的目录（可多次指定；默认 backend 的上一级即仓库根）",
    )
    args = parser.parse_args(argv)

    roots = [Path(p).resolve() for p in (args.root or [Path(__file__).resolve().parents[2]])]
    all_problems: list[str] = []
    for root in roots:
        if not root.exists():
            print(f"跳过不存在的目录: {root}")
            continue
        found = check_tree(root, args.fix)
        print(f"{root}: {'修正' if args.fix else '检查'} {len(found)} 项")
        all_problems.extend(found)

    for item in all_problems:
        print(" ", item)
    if args.fix:
        return 0
    if all_problems:
        print(f"\n共 {len(all_problems)} 项编码问题（可用 --fix 修正）")
        return 1
    print("\n编码规范检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
