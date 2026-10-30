"""汉字本轮是否真被动了：逐字比 `tools/design_cjk.bin` 的 HEAD 版与工作区版。

    .venv/bin/python work/hanzi_evidence.py

两份各约 1.8 GB 的字典不能同时待在内存里（机器 3.9 GB），所以**分两个子进程**各读一份，
各自把「码位 → 内容哈希」写成小文件，再由父进程对比。一次性脚本，跑完即弃。
"""
from __future__ import annotations

import hashlib
import pickle
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def digest(path: Path, out: Path) -> None:
    import design_cjk

    data = design_cjk.load(path)
    rows = {cp: hashlib.sha1(repr(glyph).encode()).digest() for cp, glyph in data.items()}
    out.write_bytes(pickle.dumps(rows))
    print(f"{path.name}：{len(rows)} 字")


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--digest":
        digest(Path(sys.argv[2]), Path(sys.argv[2]).with_suffix(".digest"))
        return

    import cjk_vf

    head = subprocess.run(["git", "show", "HEAD:tools/design_cjk.bin"], cwd=ROOT,
                          capture_output=True, check=True).stdout
    tmp = Path("/tmp/w/design_head.bin")
    tmp.write_bytes(head)
    for path in (tmp, ROOT / "tools/design_cjk.bin"):
        subprocess.run([sys.executable, __file__, "--digest", str(path)], cwd=ROOT, check=True)
    old = pickle.loads(tmp.with_suffix(".digest").read_bytes())
    new = pickle.loads((ROOT / "tools/design_cjk.digest").read_bytes())
    (ROOT / "tools/design_cjk.digest").unlink()

    assert set(old) == set(new), "码位集合变了"
    changed = [cp for cp in old if old[cp] != new[cp]]
    han = [cp for cp in old if cjk_vf.is_han(cp)]
    han_changed = [cp for cp in changed if cjk_vf.is_han(cp)]
    print(f"数据总字 {len(old)}：汉字 {len(han)}、非汉字 {len(old) - len(han)}")
    print(f"本轮变化 {len(changed)} 字：汉字 {len(han_changed)}、非汉字 {len(changed) - len(han_changed)}")
    print("变化的非汉字：", "".join(chr(cp) for cp in changed if not cjk_vf.is_han(cp)))
    if han_changed:
        print("变化的汉字：", "".join(chr(cp) for cp in han_changed[:40]))


if __name__ == "__main__":
    main()
