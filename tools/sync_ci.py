#!/usr/bin/env python3
"""Copy the CI sources in ``ci/workflows/`` into ``.github/workflows/``.

Editing a workflow under ``.github/`` needs GitHub's ``workflows`` permission,
which this repository's automation token does not have. The files therefore live
in ``ci/workflows/`` -- an ordinary path -- and are copied here by hand or by an
account that has the permission::

    python3 tools/sync_ci.py            # copy, then git add .github && git commit
    python3 tools/sync_ci.py --check    # exit 1 if the two trees differ (used by tests)
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "ci/workflows"
TARGET = ROOT / ".github/workflows"


def differences():
    """Every way the target tree differs from the source tree, as sentences."""
    wanted = {path.name: path for path in sorted(SOURCE.glob("*.yml"))}
    found = {path.name: path for path in sorted(TARGET.glob("*.yml"))} if TARGET.is_dir() else {}
    result = []
    for name, source in wanted.items():
        if name not in found:
            result.append(f"{name}: missing from .github/workflows")
        elif source.read_bytes() != found[name].read_bytes():
            result.append(f"{name}: differs from ci/workflows/{name}")
    for name in found:
        if name not in wanted:
            result.append(f"{name}: only in .github/workflows (remove it, or add ci/workflows/{name})")
    return result


def sync():
    """Write the source tree into the target tree, deleting what it dropped."""
    wanted = {path.name for path in SOURCE.glob("*.yml")}
    TARGET.mkdir(parents=True, exist_ok=True)
    written, removed = [], []
    for name in sorted(wanted):
        shutil.copyfile(SOURCE / name, TARGET / name)
        written.append(name)
    for path in sorted(TARGET.glob("*.yml")):
        if path.name not in wanted:
            path.unlink()
            removed.append(path.name)
    return written, removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="Report differences and exit non-zero without writing anything")
    args = parser.parse_args()
    diffs = differences()
    if args.check:
        for diff in diffs:
            print(diff)
        sys.exit(1 if diffs else 0)
    if not diffs:
        print("ci/workflows and .github/workflows already match")
        return
    written, removed = sync()
    for name in written:
        print(f"copied  ci/workflows/{name} -> .github/workflows/{name}")
    for name in removed:
        print(f"removed .github/workflows/{name}")
    print("now: git add -A .github && git commit && git push")


if __name__ == "__main__":
    main()
