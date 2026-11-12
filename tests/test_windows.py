import unittest
from PIL import Image
from dc_assistant.branding import ASSETS
from dc_assistant.windows import fitted_geometry


class PlacementTests(unittest.TestCase):
    def test_centered_over_parent(self):
        width, height, x, y = fitted_geometry(
            (500, 300), (0, 0, 1920, 1040), (400, 200, 1600, 900)
        )
        self.assertEqual((x + (width + 16) // 2, y + (height + 40) // 2), (1000, 550))

    def test_parent_near_edge_stays_inside_work_area(self):
        width, height, x, y = fitted_geometry(
            (1000, 690), (0, 40, 1920, 1040), (1500, 800, 2100, 1300)
        )
        self.assertGreaterEqual(y, 56)
        self.assertLessEqual(y + height + 40, 1024)
        self.assertLessEqual(x + width + 16, 1904)

    def test_small_screen_reduces_window_size(self):
        self.assertEqual(
            fitted_geometry((1260, 780), (0, 0, 1024, 728)), (976, 656, 16, 16)
        )

    def test_negative_second_monitor_coordinates(self):
        width, height, x, y = fitted_geometry((1000, 690), (-1920, -1080, 0, 0))
        self.assertLess(x, 0)
        self.assertLess(y, 0)
        self.assertGreaterEqual(x, -1904)
        self.assertLessEqual(x + width + 16, -16)

    def test_high_dpi_frame_space_is_reserved(self):
        width, height, x, y = fitted_geometry(
            (1000, 690), (0, 0, 1024, 728), decoration=(32, 80)
        )
        self.assertLessEqual(x + width + 32, 1008)
        self.assertLessEqual(y + height + 80, 712)

    def test_approved_icon_has_windows_sizes(self):
        with Image.open(ASSETS / "dc-assistant.ico") as icon:
            self.assertTrue(
                {(16, 16), (32, 32), (48, 48), (256, 256)} <= icon.ico.sizes()
            )


if __name__ == "__main__":
    unittest.main()
