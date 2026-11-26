#!/usr/bin/env python3
"""检讨标记机（GLOBAL.md §17／§19）：数汉字、插标记、验标记、报末行。

规范原文（§17）：当面记字＝当轮满 10000 汉字；**篇首标等级和字数**，每满 100 汉字插一枚标
（相邻两标之间必须正好 100 字）；段尾假标、虚报、几篇赖成一篇都算造假。末行报读数。
规范原文（§15）：**图不内联等于没有图。**

用法：
    python3 tools/mark.py insert <稿子.txt> [--out <带标记.txt>]
        读出正文，按**实测**汉字数每满 100 插 `〖100〗` `〖200〗` …，写出带标记稿。
    python3 tools/mark.py check <带标记.txt>
        验证：篇首有等级字数行且字数与实测一致、汉字总数 ≥10000、标记数 ≥100、
        首标前恰好 100 汉字、相邻两标之间恒 100、末标之后为余数、
        正文提到的每个 .png 至少有一处 `![…](…)` 内联。全部通过才退出 0。
    python3 tools/mark.py strip <带标记.txt>
        去掉标记，还原成可再次 insert 的纯正文。

汉字口径：`\\u3400-\\u4dbf`、`\\u4e00-\\u9fff`（含扩展 A）、`\\uf900-\\ufaff`（兼容）。
**不数**标点、不数 ASCII、不数数字；标记本身（`〔数字〕`）不计入；篇首等级行是元数据，不计入。

为什么要有这个文件：§17 的标记必须**由脚本数出**。手插的标记一律按造假处理，
所以插与验必须是同一份实现，不许两处各写一套（同源）。

2026-11-27 追加三条判据（各有一次事故）：
  ① 篇首等级字数行——part20/part21 落盘时没有，规范 §17 一直写着，我没读。
  ② 等级行声明的字数与实测一致——防「篇首写一万、正文八千」的虚报。
  ③ png 必内联——主人 2026-11-27 罚「图不内联」：落盘了图却在交付里只给路径与 sha，
     等于没有图。内联语法 ASCII（alt 与路径都不含汉字），所以不影响汉字口径。
"""
import re
import sys

HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 标号符号：规范原文是 `〖N〗`（主人 2026-11-26 再次明确）。本机曾写成 `〔N〕`，
# 两份写法都认——否则历史稿件的标记会被判成「没有标记」，那是工具在冤枉正文。
MARK = re.compile(r"[〔〖](\d+)[〕〗]")
# 篇首等级行（元数据，不计汉字）。例：`> 等级：当面记字　字数：10054（tools/mark.py 实测）`
HEAD = re.compile(r"^>\s*等级：\S+　字数：(\d+)")
PNG = re.compile(r"[\w.\-/一-鿿]+\.png")
INLINE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
PER = 100


def split_head(text: str) -> tuple[str, str]:
    """把篇首等级行（若存在）从正文里摘出来。返回 (等级行, 其余)。"""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if not ln.strip():
            continue
        if HEAD.match(ln.strip()):
            rest = "\n".join(lines[:i] + lines[i + 1:])
            return ln.strip(), rest
        return "", text
    return "", text


def han_count(text: str) -> int:
    """全部汉字个数（标记会先被剥掉，避免 `〔100〕` 里的数字干扰口径）。"""
    return len(HAN.findall(MARK.sub("", text)))


def strip_marks(text: str) -> str:
    return MARK.sub("", text)


def insert(text: str) -> str:
    """逐字符走一遍正文，每累计满 100 个汉字就在**那个汉字之后**插入当时的总数标记。

    标记插在汉字后，不改动任何原字符，因此 `strip(insert(x)) == x` 恒成立
    （自检里断言这一条：插标记不许吃掉正文）。篇首等级行原样保留、不参与计数。
    """
    head, body = split_head(text)
    out: list[str] = []
    count = 0
    for ch in body:
        out.append(ch)
        if HAN.match(ch):
            count += 1
            if count % PER == 0:
                out.append(f"〖{count}〗")
    marked = "".join(out)
    return (head + "\n" + marked) if head else marked


def check(text: str) -> tuple[bool, list[str], str]:
    """返回 (是否通过, 问题列表, 末行建议)。判据与 §15／§17／§19 逐条对应。"""
    problems: list[str] = []
    head, body = split_head(text)
    if not head:
        problems.append("篇首缺等级字数行（规范 §17：篇首标等级和字数）；"
                        "格式：`> 等级：当面记字　字数：<实测>`")
    total = han_count(body)          # 口径只有这一处实现
    if head and int(HEAD.match(head).group(1)) != total:
        problems.append(f"篇首声明字数 {HEAD.match(head).group(1)} 与实测 {total} 不一致（虚报？）")
    marks = [(m.start(), int(m.group(1))) for m in MARK.finditer(body)]

    # 三条判据，每条都有能单独观测到它的反例（都进了 build.py 的夹具，逐条变异过）：
    #     ① 标记数 ≥100 —— 反例：150 字只插出 1 枚，位置全对、也没有漏标，只有这条抓得住
    #     ② 每枚标记的位置与它声明的一致，且首标前恰好 100
    #     ③ 末枚之后不满 100（否则就是漏标）
    #   注意 ① 与「汉字 ≥10000」不等价：稿子只有 1 枚标记时两者都红，但只有 ① 能说明
    #   「你没插完」，而汉字数判据在插漏时照样能过（`insert` 漏插不改字数）。
    if len(marks) < 100:
        problems.append(f"标记数 {len(marks)} < 100：每满 100 汉字一枚，一万字至少 100 枚；"
                        f"实际汉字 {total}")

    for index, (pos, declared) in enumerate(marks, 1):
        # 第一枚：标记之前（剥掉其它标记）必须恰好 100 个汉字。
        # 第 n 枚：它声明 n*100，且与上一枚之间实测恒 100。
        before = han_count(body[:pos])
        expect = index * PER
        if declared != expect:
            problems.append(f"第 {index} 枚标着〔{declared}〕，按位置应为〔{expect}〕（标记被手改过？）")
        if before != expect:
            problems.append(f"第 {index} 枚〔{declared}〕前实测 {before} 汉字，应恰好 {expect}")

    tail = han_count(body[marks[-1][0]:]) if marks else total
    if tail >= PER:
        problems.append(f"末枚之后还有 {tail} 汉字 ≥100，漏标了 {tail // PER} 枚")

    # 图不内联等于没有图（§15）：正文点名的**现存** png，至少一处出现在 ![…](…) 里。
    # 只查现存文件：历史叙述里提到已删除的旧图名（如「fig1.png 首版是豆腐」）若也强制内联，
    # 就会逼出指向不存在文件的坏链接，违反 evidence/README「不留指向已删文件的引用」。
    # 2026-11-27 补洞：裸名（不带日期前缀）也算提及——上一版只按全名匹配，part21 里
    # 「roster-20.png」这种裸名绕过了判据，正文有图名无内联，主人再罚 10。
    inlined = set()
    for m in INLINE.finditer(body):
        inlined.add(m.group(1).rsplit("/", 1)[-1])
    import pathlib
    here = pathlib.Path(__file__).resolve().parent.parent
    existing = {p.name for p in (here / "docs" / "evidence").glob("*.png")}
    mentioned = {n.rsplit("/", 1)[-1] for n in PNG.findall(body)}
    for full in sorted(existing):
        bare = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", full)
        if (full in mentioned or bare in mentioned) and full not in inlined:
            problems.append(f"图未内联：正文提到现存的 {full}（或其裸名）但没有 ![…](…) 语法"
                            f"（规范 §15：图不内联等于没有图）")

    line = (f"本篇汉字 {total}；" + ("" if total >= 10000 else "不足一万字＝没交；") +
            f"末枚〖{marks[-1][1] if marks else 0}〗；"
            f"末枚之后余 {tail}；口径＝只数汉字（U+3400–4DBF／4E00–9FFF／F900–FAFF），不数标点与数字，"
            f"标记由 tools/mark.py 实测插入")
    return (not problems), problems, line


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("insert", "check", "strip"):
        sys.exit("用法：mark.py insert|check|strip <文件> [--out 输出]")
    mode, path = argv[0], argv[1]
    out = None
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    if mode == "insert":
        marked = insert(text)
        assert strip_marks(split_head(marked)[1]) == split_head(text)[1], "插标记吃掉了正文"
        if out:
            with open(out, "w", encoding="utf-8") as handle:
                handle.write(marked)
            ok, problems, line = check(marked)
            print(line)
            for item in problems:
                print(f"[不合格] {item}")
            print("已写出", out)
            return 0 if ok else 1
        print(marked)
        return 0

    if mode == "strip":
        head, body = split_head(text)
        sys.stdout.write((head + "\n" if head else "") + strip_marks(body))
        return 0

    ok, problems, line = check(text)
    for item in problems:
        print(f"[不合格] {item}")
    print(line)
    print("RESULT", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
