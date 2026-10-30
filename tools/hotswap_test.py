"""热切换脚本的沙箱验收：不碰真机、不碰真系统，把状态机每条路都走一遍。

做法：造一个假模块目录 + 假系统根 + 假的 `mount`/`umount`（把挂载表记在文件里），
然后按真实用法调用 `module/hotswap.sh`，逐条断言输出与退出码。

    .venv/bin/python tools/hotswap_test.py

为什么要这个脚本：热切换的失败模式都是「挂了一半」「摘了不属于自己的挂载」「状态文件
与真实挂载不一致」。这些在真机上一条条试成本太高，而它们在脚本层面全是可判定的——
把 `mount` 换成一个记账的假命令，就能在几秒内跑完全部分支。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "module/hotswap.sh"
PASS, FAIL = [], []


def build_fixture(tmp: Path) -> dict:
    """假模块 + 假系统 + 假 mount/umount。返回给 subprocess 用的环境变量。"""
    mod = tmp / "mod"
    (mod / "system/fonts").mkdir(parents=True)
    (mod / "system/etc").mkdir(parents=True)
    (mod / "system/system_ext/etc").mkdir(parents=True)
    (mod / "system/fonts/SelfroundsCJK-VF.ttf").write_bytes(b"\x00\x01\x00\x00" + b"font" * 64)
    (mod / "system/fonts/P-Regular.ttf").write_bytes(b"\x00\x01\x00\x00" + b"base" * 32)
    (mod / "system/etc/font_fallback.xml").write_text("<families/>\n")
    (mod / "system/system_ext/etc/fonts_base.xml").write_text("<families/>\n")
    shutil.copy(SCRIPT, mod / "hotswap.sh")

    root = tmp / "root"
    (root / "system/fonts").mkdir(parents=True)
    (root / "system/etc").mkdir(parents=True)
    (root / "system/system_ext/etc").mkdir(parents=True)
    (root / "system/fonts/SelfroundsCJK-VF.ttf").write_bytes(b"stock")
    (root / "system/fonts/P-Regular.ttf").write_bytes(b"stock")
    (root / "system/etc/font_fallback.xml").write_text("<stock/>\n")
    (root / "system/system_ext/etc/fonts_base.xml").write_text("<stock/>\n")

    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    table = tmp / "mounts.txt"
    table.write_text("")
    mount = bin_dir / "mount"
    mount.write_text(f"""#!/bin/sh
tab="{table}"
if [ "$#" -eq 1 ] || [ "$#" -eq 0 ]; then cat "$tab"; exit 0; fi
# mount --bind SRC DST
echo "$1 on $3 type none (rw,bind)" >> "$tab"
cp "$2" "$3" 2>/dev/null
exit 0
""")
    umount = bin_dir / "umount"
    umount.write_text(f"""#!/bin/sh
tab="{table}"
if ! grep -q " $1 " "$tab" 2>/dev/null; then echo "umount: $1: not mounted" >&2; exit 1; fi
grep -v " on $1 " "$tab" > "$tab.tmp"; mv "$tab.tmp" "$tab"
exit 0
""")
    for f in (mount, umount):
        f.chmod(0o755)
    env = dict(os.environ)
    env.update({
        "SELFFONT_SYSTEM_ROOT": str(root),
        "SELFFONT_STATE": str(tmp / "state.txt"),
        "SELFFONT_NSENTER": "",
        "SELFFONT_RELOAD": "none",
        "PATH": f"{bin_dir}:{env.get('PATH', '')}",
    })
    return env


def run(env: dict, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["sh", "hotswap.sh", *args], cwd=env["SELFFONT_SYSTEM_ROOT"] and str(Path(env["SELFFONT_STATE"]).parent / "mod"),
                          capture_output=True, text=True, env=env)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def expect(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'} {name}{('  ' + detail) if detail and not cond else ''}")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env = build_fixture(tmp)

        code, out = run(env, "status")
        expect("初始状态是 off", code == 0 and out.strip() == "off", out)

        code, out = run(env, "on")
        expect("on 挂上全部文件", code == 0 and "挂上 4 个文件" in out, out)
        expect("状态文件逐行记账", len(Path(env["SELFFONT_STATE"]).read_text().split()) == 4)

        code, out = run(env, "status")
        expect("on 之后状态是 on", out.strip() == "on", out)

        code, out = run(env, "on")
        expect("重复 on 是空操作", code == 0 and "已经是 on" in out, out)

        code, out = run(env, "verify")
        expect("verify 全一致", code == 0 and "一致 4，不一致 0" in out, out)

        code, out = run(env, "off")
        expect("off 摘下全部", code == 0 and "摘下 4 个文件" in out, out)
        code, out = run(env, "status")
        expect("off 之后状态是 off", out.strip() == "off", out)
        code, out = run(env, "off")
        expect("重复 off 是空操作", "已经是 off" in out, out)

        code, out = run(env, "toggle")
        expect("toggle 从 off 到 on", "挂上" in out, out)
        code, out = run(env, "toggle")
        expect("toggle 从 on 到 off", "摘下" in out, out)

        # 部分失败：第三个文件挂不上 → 状态 partial，off 仍能摘干净
        env_fail = dict(env)
        env_fail["SELFFONT_FAKE_FAIL"] = "fonts_base.xml"
        code, out = run(env_fail, "on")
        expect("部分失败返回非零并说明", code != 0 and "部分失败" in out, out)
        code, out = run(env, "status")
        expect("部分失败时状态是 partial", out.strip() == "partial", out)
        code, out = run(env, "off")
        expect("partial 之后 off 能摘干净", code == 0 and "摘下" in out, out)
        code, out = run(env, "status")
        expect("清理后回到 off", out.strip() == "off", out)

        # 干跑：不写状态、不执行 mount
        code, out = run(env, "on", "--dry-run")
        expect("dry-run 只打印", code == 0 and "[dry-run] mount --bind" in out and "未改动系统" in out, out)
        expect("dry-run 不留状态文件", not Path(env["SELFFONT_STATE"]).exists())

        # 模块里没有 system/ 时给出人话
        empty_mod = tmp / "empty-mod"
        empty_mod.mkdir()
        shutil.copy(SCRIPT, empty_mod / "hotswap.sh")
        env_empty = dict(env)
        env_empty["SELFFONT_STATE"] = str(tmp / "state-empty.txt")
        proc = subprocess.run(["sh", "hotswap.sh", "on"], cwd=str(empty_mod),
                              capture_output=True, text=True, env=env_empty)
        out = (proc.stdout + proc.stderr).strip()
        expect("模块里没有字件时报错而不是乱挂", proc.returncode != 0 and "没有" in out, out)

    print(f"\n{len(PASS)} 项通过，{len(FAIL)} 项失败")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
