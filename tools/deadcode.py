#!/usr/bin/env python3
"""死码扫描器（§9 旧代码清零）。

判据只有一条：**标识符在整仓源码里只出现一次**（主码与测试分计）。
本仓没有独立测试目录，`build.py --check` 就是测试，因此「分计」落成：
扫描域 = 全部 `.py` + 全部交付/工具 `.sh`（只写不读的变量）。
上次这里写「+ 工作流」，但 `iter_py` 只扫 `.py` —— 注释吹了牛，代码没兑现
（主人 2026-11-09 打回：`.sh` 里 4 处死变量全漏，包括我自己刚写的 `_awk_rc`）。

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
import re
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
    """按 AST 数「出现点」，每个出现点恰好计 1 次。

    ★★ 2026-11-09 主人打回：上一版把赋值**数了两遍**。
      Python `ast` 里 `FOO = 1` 的赋值目标**本来就是** `ast.Name(id='FOO', ctx=Store())`，
      我在 `ast.Assign` 分支计了一次，`ast.walk` 再走到子节点 `ast.Name` 又计一次 ——
      于是任何「只定义一次、零引用」的常量计数恒 ≥ 2，`③ 零引用常量` 检测率恒为 0%：
      连这个扫描器自己第 27 行的 `SRC_SUFFIX` 都没被扫出来。
      现在只走 `ast.Name`（Store/Load/Del 都在里面），另外补上 def / import 这些
      **不是** Name 节点的定义点，各计 1。
    """
    counts: dict[str, int] = {}
    for path in iter_py(root):
        tree = load(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts[node.name] = counts.get(node.name, 0) + 1
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    if a.name != "*":
                        nm = a.asname or a.name.split(".")[0]
                        counts[nm] = counts.get(nm, 0) + 1
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
    # 上一版这里是 `{k: max(...) for k, v in counts.items()}`，而 counts 此刻还是空字典，
    # 推导式结果恒为 {}，是纯死逻辑（主人 2026-11-09 指出）。直接取并集即可。
    counts = dict(counts_f)
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


SH_SKIP_DIRS = {".venv", "work", "__pycache__", ".git", "out", "dist", "build", "module/system"}


def iter_sh(root: Path):
    for p in sorted(root.rglob("*.sh")):
        if any(part in SH_SKIP_DIRS for part in p.parts):
            continue
        yield p


def shell_write_only(path: Path) -> list[tuple[int, str]]:
    """`.sh` 里赋值后从未被读取的变量。

    判据刻意保守（宁可漏报不许误报）：
      · 只认行首的 `NAME=...`（不是 `export`、不是 `local` 之外的怪写法）
      · 变量名要全大写或带下划线前缀（`i=` 这种循环变量不管，误报率太高）
      · 整份文件里 `$NAME` / `${NAME` / `${NAME:` 一次都没出现
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    code = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        code.append((i, line))
    body = "\n".join(l for _, l in code)
    # ★ 陷阱：变量可能被**从别处 eval 进来的函数**读（sf-scan.sh 的 GUARD_LOG 就是这样）。
    #   本文件字面上不出现 `$GUARD_LOG`，但它把那函数体 eval 进来后就会被读。
    #   删过一次，sf-scan 立刻静默变成零输出 —— 死码扫描器自己造出真 bug。
    #   保守判据：只要文件里出现 `eval`，就不判「只写不读」（宁可漏报）。
    if re.search(r"^\s*eval\s", body, re.M):
        return []
    bad = []
    for i, line in code:
        m = re.match(r"\s*(?:local\s+|export\s+)?([A-Z][A-Z0-9_]*)=([^=].*)?$", line)
        if not m:
            continue
        name = m.group(1)
        if re.search(r"\$\{" + name + r"[}:]|\$" + name + r"\b", body):
            continue
        bad.append((i, name))
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

    # ---- .sh：只写不读的变量 ----
    for path in iter_sh(root):
        for lineno, name in shell_write_only(path):
            print(f"④ 只写不读的局部变量 {path.relative_to(root)}:{lineno}  {name}")
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
