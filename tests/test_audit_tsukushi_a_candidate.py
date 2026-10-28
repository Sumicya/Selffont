import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools.audit_tsukushi_a_candidate import _iou, _render_metrics, write_csv, write_markdown


class RasterAuditMetricTests(unittest.TestCase):
    def test_render_metrics_counts_components_counters_and_bbox(self):
        mask = np.zeros((11, 11), dtype=bool)
        mask[1:8, 1:8] = True
        mask[3:6, 3:6] = False
        mask[9, 9] = True

        metrics = _render_metrics(mask)

        self.assertEqual(metrics.components, 2)
        self.assertEqual(metrics.holes, 1)
        self.assertEqual(metrics.bbox, (1, 1, 10, 10))
        self.assertEqual(metrics.area_px, 41)

    def test_iou_handles_identical_and_disjoint_masks(self):
        left = np.array([[True, False], [False, True]])
        right = np.array([[False, True], [True, False]])

        self.assertEqual(_iou(left, left), 1.0)
        self.assertEqual(_iou(left, right), 0.0)

    def test_report_does_not_link_to_unrequested_csv(self):
        summary = {
            "candidate_label": "V10",
            "redrawn_geometry_chars": ["鸟"],
            "redrawn_geometry_topology_changes": ["鸟 U+9E1F: source → geometry 3/0 → 1/0"],
            "sample_entries": 1,
            "unique_glyphs": 1,
            "renderer_versions": {"pillow": "test", "freetype": "test", "fonttools": "test"},
            "large_render_px_per_em": 1000,
            "topology_errors": [],
            "advance_errors": [],
            "mapping_errors": [],
            "small_size_topology_differences_source_vs_candidate": 0,
            "small_size_topology_difference_codepoints": [],
            "small_render_px_per_em": 48,
            "electric_advances_fu": {"source": 950, "geometry": 950, "candidate": 950},
            "electric_bbox_widths_fu": {"source": 819, "geometry": 819, "candidate": 814},
            "electric_x_bounds_fu": {"source": (111, 930), "candidate": (108, 922)},
            "width_summaries": {
                role: {
                    "glyphs": 1,
                    "median_of_medians_fu": 74.0,
                    "across_glyph_cv": 0.0,
                    "within_glyph_cv_mean": 0.0,
                    "within_glyph_cv_max": 0.0,
                }
                for role in ("source", "geometry", "candidate")
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "audit.md"
            write_markdown(report, summary, None)
            content = report.read_text(encoding="utf-8")

        self.assertIn("No CSV was requested for this run.", content)
        self.assertIn("# V10 sample-wide raster/topology audit", content)
        self.assertIn("Intentional source-to-geometry redraw allowance: 鸟.", content)
        self.assertIn("鸟 U+9E1F: source → geometry 3/0 → 1/0", content)
        self.assertNotIn("sample-audit.csv", content)

    def test_csv_writer_uses_clean_utf8_lf_lines(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "audit.csv"
            write_csv(csv_path, [{"character": "鸟", "sample_index": 1}])
            content = csv_path.read_bytes()

        self.assertFalse(content.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", content)
        self.assertIn("鸟".encode("utf-8"), content)


if __name__ == "__main__":
    unittest.main()
