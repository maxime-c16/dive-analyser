import unittest

from audit_localization_authority import assess
from localization_review import validate_label
from repair_annotation_timebase import displayed_frame


class LocalizationAuthorityTests(unittest.TestCase):
    def test_displayed_frame_uses_pts_not_average_fps(self):
        self.assertEqual(displayed_frame([0, .02, .04, .10, .12], .09), 2)
        self.assertEqual(displayed_frame([0, .02, .04, .10, .12], .10), 3)

    def test_outside_pts_is_rejected(self):
        for timestamp in (-1, .2):
            with self.assertRaises(ValueError):
                displayed_frame([0, .02, .04], timestamp)

    def test_timebase_conflict(self):
        result = assess(291, 4.853569, 30000 / 1001, 222)
        self.assertTrue(result["frame_out_of_bounds"])
        self.assertFalse(result["consistent_with_media_fps"])

    def test_rounding_is_not_a_conflict(self):
        self.assertTrue(assess(145, 4.853569, 30000 / 1001, 222)["consistent_with_media_fps"])

    def test_visible_requires_nonempty_finite_box(self):
        row = {"width": 202, "height": 360}
        for box in (None, [1, 1, 1, 10], [0, 0, 203, 20], [0, 0, float("nan"), 20]):
            with self.assertRaises(ValueError):
                validate_label({"visibility": "visible", "bbox": box}, row)

    def test_ambiguous_requires_reason(self):
        with self.assertRaises(ValueError):
            validate_label({"visibility": "ambiguous"}, {"width": 202, "height": 360})

    def test_invisible_has_no_box(self):
        row = {"width": 202, "height": 360}
        self.assertEqual(validate_label({"visibility": "occluded"}, row)["bbox"], None)
        with self.assertRaises(ValueError):
            validate_label({"visibility": "occluded", "bbox": [0, 0, 10, 10]}, row)

    def test_review_provenance_cannot_be_spoofed_by_payload(self):
        result = validate_label({"visibility": "visible", "bbox": [0, 0, 10, 10],
                                 "annotator": "auto", "state": "AUTO"}, {"width": 202, "height": 360})
        self.assertEqual(result["annotator"], "maxime")
        self.assertEqual(result["state"], "HUMAN_REVIEWED")


if __name__ == "__main__":
    unittest.main()
