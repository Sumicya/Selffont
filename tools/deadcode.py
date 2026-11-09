#!/usr/bin/env python3
"""死码扫描器（§9 旧代码清零）。

判据只有一条：**标识符在整仓源码里只出现一次**（主码与测试分计）。
本仓没有独立测试目录，`build.py --check` 就是测试，因此「分计」落成：
扫描域 = 全部 `.py` + `.sh` + 工作流 + 文档以外的一切源码，
引用计数按**整仓**统计（跨文件调用也算引用，宁可漏报不许误删）。

报四类：
  ① 未使用的 import（`from __future__` 除外：它由编译器隐式使用）
  ② 定义了但整仓只出现一次的函数
  ③ 模块级常量只赋值、从不被引用
  ④ 只写不读的局部变量（赋值后在该作用域内再未被读）

退出码：发现任一类即 1（接进 build.py --check 与 CI 必须非 0）。
盲区写在最后，必须列清，不许假装扫全了：
  · 字符串里的动态引用（getattr / globals()[...]）
  · 只在 shell 或工作流里被调用的脚本函数（本仓无此用法）
  · 类型注解里出现一次的名字（rdflib 之类前向引用）
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC_SUFFIX = {".py"}
SKIP_DIRS = {".venv", "work", "__pycache__", ".git", "out", "dist", "build"}
FUTURE_ONLY = {"annotations"}          # from __future__ import annotations


def iter_py(root: Path):
    for p in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        yield p


def load(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:                     # 解析不了要明说，不许跳过
        print(f"[跳过] {path}: 语法错误 {exc}")
        return None


def ast_name_counts(root: Path) -> dict[str, int]:
    """按 AST 数名字：f-string 里的 `{NAME}` 是 Name 节点，会被算进来；
    纯文本里出现的同名子串不会被误算。

    ★ Name 节点只覆盖**读取**（Load）。赋值目标、def、import 都是别的节点类型，
    所以这里还要把函数定义、赋值目标各计一次，否则「定义 + 一次调用」会被数成 1，
    每个函数都成了死码（第一版就这么误报了 16 个装饰器注册的检查项）。"""
    counts: dict[str, int] = {}
    for path in iter_py(root):
        tree = load(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts[node.name] = counts.get(node.name, 0) + 1
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        counts[tgt.id] = counts.get(tgt.id, 0) + 1
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                counts[node.target.id] = counts.get(node.target.id, 0) + 1
            if isinstance(node, ast.Name):
                counts[node.id] = counts.get(node.id, 0) + 1
            elif isinstance(node, ast.Attribute):
                n = node
                while isinstance(n, ast.Attribute):
                    n = n.value
                if isinstance(n, ast.Name):
                    counts[n.id] = counts.get(n.id, 0) + 1
    return counts


def name_references(tree: ast.AST) -> set[str]:
    """一个文件里所有被读到的名字（含属性链根部与注解）。"""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            n = node
            while isinstance(n, ast.Attribute):
                n = n.value
            if isinstance(n, ast.Name):
                out.add(n.id)
        elif isinstance(node, ast.arg):            # 形参名也算引用（避免误报常量）
            out.add(node.arg)
    return out


def unused_imports(path: Path, tree: ast.AST) -> list[tuple[int, str]]:
    found = []
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported[a.asname or a.name.split(".")[0]] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            for a in node.names:
                if a.name != "*":
                    imported[a.asname or a.name] = node.lineno
    used = name_references(tree)
    for name, lineno in imported.items():
        if name in used or name in FUTURE_ONLY:
            continue
        found.append((lineno, name))
    return found


def module_level(tree: ast.AST):
    """模块级函数与常量名。"""
    funcs, consts = [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append((node.lineno, node.name))
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id.isupper():
                    consts.append((node.lineno, tgt.id))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id.isupper():
            consts.append((node.lineno, node.target.id))
    return funcs, consts


def repo_mention_counts(root: Path) -> dict[str, int]:
    """整仓源码里每个标识符出现的行数（跨文件也算）。"""
    counts: dict[str, int] = {}
    # 函数/常量名在 **f-string 里**是 `Name` 节点，但在普通字符串拼接里会被 _strip_strings 抹掉，
    # 「定义一行 + f-string 里用一次」就会误报成只出现一次。取两者较大值。
    counts_f = repo_mention_counts_raw(root)
    counts = {k: max(v, counts_f.get(k, 0)) for k, v in counts.items()}
    counts.update({k: v for k, v in counts_f.items() if k not in counts})
    # 再取 AST 计数：函数名/常量名在 f-string 里是 Name 节点，字符串剥离会把它抹掉。
    counts_a = ast_name_counts(root)
    counts = {k: max(v, counts_a.get(k, 0)) for k, v in counts.items()}
    counts.update({k: v for k, v in counts_a.items() if k not in counts})
    return counts


def repo_mention_counts_raw(root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in iter_py(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue                            # 注释不算引用
            for tok in _tokens(_strip_strings(stripped)):
                counts[tok] = counts.get(tok, 0) + 1
    return counts


def _strip_strings(line: str) -> str:
    """去掉字符串字面量：装饰器注册名、日志文案里出现的名字不算「被引用」。"""
    out, i, n = [], 0, len(line)
    quote = None
    while i < n:
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _tokens(line: str):
    cur, out = "", []
    for ch in line:
        if ch.isalnum() or ch == "_":
            cur += ch
        else:
            if cur:
                out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def write_only_locals(tree: ast.AST) -> list[tuple[int, str]]:
    """函数内赋值后从未被读的局部名（只写不读）。"""
    bad = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        assigned: dict[str, int] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        assigned.setdefault(tgt.id, node.lineno)
        reads = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                reads.add(node.id)
            elif isinstance(node, ast.Attribute):
                n = node
                while isinstance(n, ast.Attribute):
                    n = n.value
                if isinstance(n, ast.Name):
                    reads.add(n.id)
        for name, lineno in assigned.items():
            if name == "_" or name.startswith("_"):
                continue                            # `_` / `_tmp` 是有意的丢弃
            if name not in reads:
                bad.append((lineno, name))
    return bad


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    counts = repo_mention_counts(root)
    total = 0

    print(f"死码扫描  根目录 = {root}")
    print(f"源码文件 = {sum(1 for _ in iter_py(root))} 个 .py")

    for path in iter_py(root):
        tree = load(path)
        if tree is None:
            total += 1
            continue
        rel = path.relative_to(root)

        for lineno, name in unused_imports(path, tree):
            print(f"① 未使用 import      {rel}:{lineno}  {name}")
            total += 1

        funcs, consts = module_level(tree)
        decorated = {n.name for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.decorator_list}
        for lineno, name in funcs:
            if name.startswith("__") or name == "main" or name in decorated:
                continue
            # 判据：出现次数 ≤1，即「只有 def 这一行」。定义+一次调用是 2。
            if counts.get(name, 0) <= 1:
                print(f"② 零调用函数         {rel}:{lineno}  {name}")
                total += 1
        for lineno, name in consts:
            if counts.get(name, 0) <= 1:
                print(f"③ 零引用常量         {rel}:{lineno}  {name}")
                total += 1

        for lineno, name in write_only_locals(tree):
            print(f"④ 只写不读的局部变量 {rel}:{lineno}  {name}")
            total += 1

    print()
    print("盲区（这些不算通过，只是本工具不查）：")
    print("  · 字符串里的动态引用（getattr / globals()[...]）")
    print("  · 只在 shell / 工作流里被调用的名字")
    print("  · 前向引用注解里只出现一次的名字")
    print()
    if total:
        print(f"合计 {total} 处死码 → 失败")
        return 1
    print("合计 0 处死码 → 通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
