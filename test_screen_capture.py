import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.vision.screen_capture import ScreenCapture


class ScreenCaptureTests(unittest.TestCase):
    def test_captures_configured_region(self):
        screen = Mock()
        screen.monitors = [{"left": 0, "top": 0, "width": 10, "height": 8}]
        screen.grab.return_value = SimpleNamespace(
            size=(2, 1),
            rgb=bytes((255, 0, 0, 0, 255, 0)),
        )
        context = Mock()
        context.__enter__ = Mock(return_value=screen)
        context.__exit__ = Mock(return_value=False)

        with patch("app.vision.screen_capture.mss.mss", return_value=context):
            image = ScreenCapture.capture_region(
                {"x": 3, "y": 2, "width": 2, "height": 1}
            )

        self.assertEqual(image.size, (2, 1))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
        screen.grab.assert_called_once_with(
            {"left": 3, "top": 2, "width": 2, "height": 1}
        )

    def test_rejects_region_outside_screen_bounds(self):
        screen = Mock()
        screen.monitors = [{"left": 0, "top": 0, "width": 10, "height": 8}]
        context = Mock()
        context.__enter__ = Mock(return_value=screen)
        context.__exit__ = Mock(return_value=False)

        with patch("app.vision.screen_capture.mss.mss", return_value=context):
            with self.assertRaisesRegex(ValueError, "outside"):
                ScreenCapture.capture_region(
                    {"x": 9, "y": 2, "width": 2, "height": 1}
                )


if __name__ == "__main__":
    unittest.main()
