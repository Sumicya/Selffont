"""CI sources stay in step with the workflows that actually run.

The workflow files have to live in ``.github/workflows`` to run, but that path
needs GitHub's ``workflows`` permission to change, which the automation token
does not have. They are therefore edited in ``ci/workflows`` and copied across;
this test is what stops the two copies from drifting apart unnoticed.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import sync_ci


class CiWorkflowTests(unittest.TestCase):
    def test_the_workflow_tree_matches_its_source(self):
        self.assertEqual(sync_ci.differences(), [],
                         "run python3 tools/sync_ci.py to copy ci/workflows into .github/workflows")

    def test_sync_reports_a_missing_and_an_extra_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / "ci", root / "gh"
            source.mkdir(), target.mkdir()
            (source / "wanted.yml").write_text("name: wanted\n")
            (target / "extra.yml").write_text("name: extra\n")
            saved = sync_ci.SOURCE, sync_ci.TARGET
            sync_ci.SOURCE, sync_ci.TARGET = source, target
            try:
                self.assertEqual(sorted(sync_ci.differences()),
                                 ["extra.yml: only in .github/workflows (remove it, or add ci/workflows/extra.yml)",
                                  "wanted.yml: missing from .github/workflows"])
                written, removed = sync_ci.sync()
            finally:
                sync_ci.SOURCE, sync_ci.TARGET = saved
            self.assertEqual(written, ["wanted.yml"])
            self.assertEqual(removed, ["extra.yml"])
            self.assertEqual((target / "wanted.yml").read_text(), "name: wanted\n")
            self.assertFalse((target / "extra.yml").exists())

    def test_the_module_workflow_builds_the_extended_faces(self):
        text = (ROOT / "ci/workflows/build-module.yml").read_text()
        for step in ("tools/prepare_font.py", "tools/prepare_reference.py", "tools/extend_font.py",
                     "tools/edit_font.py", "tools/build_module.py", "tools/module_report.py"):
            self.assertIn(step, text, f"the module workflow no longer runs {step}")
        self.assertNotIn("phase1", text)
        # The deleted workflow pointed at tools/fontslist/urls.txt, which is gone.
        self.assertFalse((ROOT / ".github/workflows/build.yml").exists())

    def test_the_module_workflow_is_valid_yaml(self):
        try:
            import yaml
        except ImportError:  # pragma: no cover - pyyaml is optional
            self.skipTest("pyyaml is not installed")
        for path in sorted((ROOT / "ci/workflows").glob("*.yml")):
            data = yaml.safe_load(path.read_text())
            self.assertIn("jobs", data, f"{path.name} has no jobs")
            self.assertIsInstance(json.dumps(data), str)


if __name__ == "__main__":
    unittest.main()
