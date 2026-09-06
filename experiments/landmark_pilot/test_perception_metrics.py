import unittest
from perception_diagnostics import iou, localization_metrics


class MetricsTests(unittest.TestCase):
    def test_absent_detection_is_miss(self):
        m = localization_metrics([0, 0, 10, 20], [])
        self.assertFalse(m["recalled_iou50"])
        self.assertFalse(m["recalled_center_half_diagonal"])

    def test_absent_reference_is_not_a_miss(self):
        self.assertFalse(localization_metrics(None, [])["evaluable"])

    def test_small_box_center_and_overlap_are_distinct(self):
        m = localization_metrics([0, 0, 4, 4], [{"xyxy": [2, 0, 6, 4], "conf": .8}])
        self.assertFalse(m["recalled_iou50"])
        self.assertTrue(m["recalled_center_half_diagonal"])
        self.assertEqual(m["closest_center_candidate"]["center_error_px"], 2)

    def test_iou_geometry(self):
        self.assertEqual(iou([0, 0, 10, 20], [0, 0, 10, 20]), 1)
        self.assertEqual(iou([0, 0, 10, 20], [10, 0, 20, 20]), 0)


if __name__ == "__main__":
    unittest.main()
