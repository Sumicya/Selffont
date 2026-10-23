import unittest

import numpy as np
import shapely.geometry as sg
from scipy import ndimage
from skimage.morphology import skeletonize

from tools.stroke_width_normalize_prototype import (
    glyph_from_mask,
    shared_width_reconstruction_mask,
    transform_skeleton_x,
    transform_skeleton_x_profiled,
)


class SharedWidthTopologyTests(unittest.TestCase):
    def setUp(self):
        self.mask = np.zeros((26, 20), dtype=bool)
        self.mask[3:23, 4:7] = True
        self.mask[3:23, 11:14] = True
        self.skeleton = skeletonize(self.mask)

    def test_optional_guard_keeps_nearby_source_components_separate(self):
        raw = shared_width_reconstruction_mask(
            self.mask, self.skeleton, target_width=10.0, units_per_pixel=1.0
        )
        guarded = shared_width_reconstruction_mask(
            self.mask,
            self.skeleton,
            target_width=10.0,
            units_per_pixel=1.0,
            preserve_components=True,
        )

        self.assertEqual(ndimage.label(raw, structure=np.ones((3, 3)))[1], 1)
        self.assertEqual(ndimage.label(guarded, structure=np.ones((3, 3)))[1], 2)
        self.assertTrue(np.all(guarded[self.skeleton]))
        self.assertLess(guarded.sum(), raw.sum())

    def test_guard_does_not_change_reconstruction_when_components_do_not_overlap(self):
        raw = shared_width_reconstruction_mask(
            self.mask, self.skeleton, target_width=4.0, units_per_pixel=1.0
        )
        guarded = shared_width_reconstruction_mask(
            self.mask,
            self.skeleton,
            target_width=4.0,
            units_per_pixel=1.0,
            preserve_components=True,
        )
        np.testing.assert_array_equal(guarded, raw)

    def test_guard_validates_shapes_and_width_inputs(self):
        with self.assertRaisesRegex(ValueError, "same-sized 2D"):
            shared_width_reconstruction_mask(
                self.mask, self.skeleton[:, :-1], 10.0, 1.0, preserve_components=True
            )
        for width in (0.0, -1.0, float("inf")):
            with self.subTest(width=width), self.assertRaisesRegex(ValueError, "target_width"):
                shared_width_reconstruction_mask(
                    self.mask, self.skeleton, width, 1.0, preserve_components=True
                )


class SkeletonCompressionTests(unittest.TestCase):
    def test_compresses_frame_spacing_about_centerline_and_leaves_other_rows(self):
        skeleton = np.zeros((15, 15), dtype=bool)
        skeleton[1:14, 2] = True
        skeleton[1:14, 7] = True
        skeleton[1:14, 12] = True
        skeleton[8, 2:13] = True
        transform = (0.0, 0.0, 1.0, 0.0, 1.0, 1)

        result = transform_skeleton_x(
            skeleton, transform, center_x=7.0, y_min=3.0, y_max=12.0, scale_x=0.5
        )

        # Font y=7 maps to raster row 8. Both side strokes move equally inward;
        # the central divider remains on x=7. Raster rounding may differ by 1 px.
        self.assertTrue(result[8, 5])
        self.assertTrue(result[8, 7])
        self.assertTrue(result[8, 10])
        self.assertFalse(result[8, 2])
        self.assertFalse(result[8, 12])
        # Raster row 1 maps outside the selected font-y band and remains unchanged.
        np.testing.assert_array_equal(result[1], skeleton[1])
        self.assertTrue(result[:, 7].any())

    def test_profiled_compression_preserves_frame_extrema_and_centerline(self):
        skeleton = np.zeros((15, 15), dtype=bool)
        skeleton[1:14, 2] = True
        skeleton[1:14, 7] = True
        skeleton[1:14, 12] = True
        skeleton[8, 2:13] = True
        transform = (0.0, 0.0, 1.0, 0.0, 1.0, 1)

        result = transform_skeleton_x_profiled(
            skeleton,
            transform,
            center_x=7.0,
            y_min=2.0,
            y_max=12.0,
            scale_x=0.5,
            edge_fraction=0.2,
        )

        # Font y=7 maps to raster row 8 and reaches peak compression. The axis stays
        # fixed; the upper/lower frame bounds (rows 3 and 13) remain full width.
        self.assertTrue(result[8, 5])
        self.assertTrue(result[8, 7])
        self.assertTrue(result[8, 10])
        self.assertFalse(result[8, 2])
        self.assertFalse(result[8, 12])
        np.testing.assert_array_equal(result[3], skeleton[3])
        np.testing.assert_array_equal(result[13], skeleton[13])

    def test_rejects_invalid_scale_and_y_range(self):
        skeleton = np.eye(9, dtype=bool)
        transform = (0.0, 0.0, 1.0, 0.0, 1.0, 1)
        for scale_x in (0.0, -0.1, 1.1, float("inf")):
            with self.subTest(scale_x=scale_x), self.assertRaises(ValueError):
                transform_skeleton_x(skeleton, transform, 4.0, 1.0, 7.0, scale_x)
        with self.assertRaisesRegex(ValueError, "y_min < y_max"):
            transform_skeleton_x(skeleton, transform, 4.0, 7.0, 1.0, 0.9)

    def test_rejects_non_square_and_empty_skeletons(self):
        transform = (0.0, 0.0, 1.0, 0.0, 1.0, 1)
        with self.assertRaisesRegex(ValueError, "square 2D"):
            transform_skeleton_x(np.zeros((4, 5), dtype=bool), transform, 2, 1, 3, 0.9)
        with self.assertRaisesRegex(ValueError, "empty skeleton"):
            transform_skeleton_x(np.zeros((5, 5), dtype=bool), transform, 2, 1, 3, 0.9)


class RasterOutlineRepairTests(unittest.TestCase):
    def test_diagonal_pixel_join_is_traced_as_valid_contours(self):
        class FontStub:
            @staticmethod
            def getGlyphSet():
                return {}

        mask = np.zeros((12, 12), dtype=bool)
        mask[1:5, 1:5] = True
        mask[5:9, 5:9] = True
        transform = (0.0, 0.0, 1.0, 0.0, 1.0, 1)

        glyph = glyph_from_mask(mask, FontStub(), transform)
        coordinates, ends, _flags = glyph.getCoordinates(None)

        self.assertEqual(len(ends), 2)
        start = 0
        for end in ends:
            polygon = sg.Polygon([tuple(point) for point in coordinates[start:end + 1]])
            self.assertTrue(polygon.is_valid)
            self.assertGreater(polygon.area, 0)
            start = end + 1


if __name__ == "__main__":
    unittest.main()
