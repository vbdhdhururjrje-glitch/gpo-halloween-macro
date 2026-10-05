import mss
from PIL import Image


class ScreenCapture:
    @staticmethod
    def capture_region(region):
        if not isinstance(region, dict):
            raise ValueError("OCR region must be an object.")
        try:
            left = int(region["x"])
            top = int(region["y"])
            width = int(region["width"])
            height = int(region["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("OCR region requires integer x, y, width, and height.") from exc
        if width <= 0 or height <= 0:
            raise ValueError("OCR region width and height must be positive.")

        with mss.mss() as screen:
            bounds = screen.monitors[0]
            if (
                left < bounds["left"]
                or top < bounds["top"]
                or left + width > bounds["left"] + bounds["width"]
                or top + height > bounds["top"] + bounds["height"]
            ):
                raise ValueError("OCR region is outside the available screen bounds.")
            frame = screen.grab({"left": left, "top": top, "width": width, "height": height})
        return Image.frombytes("RGB", frame.size, frame.rgb)
