import json
import math
from pathlib import Path


CONFIG_DIR = Path.home() / "GPO_Halloween_Macro"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
ROUTE_FILE = CONFIG_DIR / "route.json"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
OCR_DEFAULT_REGION = {"x": 440, "y": 192, "width": 500, "height": 48}


class ConfigManager:
    DEFAULTS = {
        "bag_slot": 4,
        "startup_delay": 1.0,
        "playback_speed": 1.0,
        "repeat_delay": 5.0,
        "door_retry_interval": 5.0,
        "door_e_press_limit": 5,
        "ocr_scan_interval": 0.5,
        "ocr_frame_interval": 0.05,
        "mouse_gain": 1.0,
        "route_path": "",
        "language": "RU",
        "hotkeys": {
            "start": "F6",
            "pause": "F7",
            "stop": "F8",
            "emergency": "F12",
            "mark": "F9",
            "record": "F10",
        },
        "ocr": {
            "region": OCR_DEFAULT_REGION,
            "tesseract_cmd": "",
        },
        "door_cooldowns": {},
    }

    def load(self):
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Settings must be a JSON object.")
        except FileNotFoundError:
            data = {}
        except (json.JSONDecodeError, ValueError):
            data = {}
        return self._merge_defaults(data)

    def save(self, data):
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def default_settings(cls):
        return cls._merge_defaults({})

    @classmethod
    def _merge_defaults(cls, data):
        if not isinstance(data, dict):
            data = {}
        merged = dict(cls.DEFAULTS)
        hotkeys = data.get("hotkeys", {})
        ocr = data.get("ocr", {})
        door_cooldowns = data.get("door_cooldowns", {})
        if not isinstance(hotkeys, dict):
            hotkeys = {}
        if not isinstance(ocr, dict):
            ocr = {}
        if not isinstance(door_cooldowns, dict):
            door_cooldowns = {}
        merged["hotkeys"] = {
            key: value.strip()
            if isinstance(value, str) and value.strip()
            else default
            for key, default in cls.DEFAULTS["hotkeys"].items()
            for value in (hotkeys.get(key, default),)
        }
        ocr_region = ocr.get("region", {})
        if not isinstance(ocr_region, dict):
            ocr_region = {}
        merged["ocr"] = {
            **cls.DEFAULTS["ocr"],
            "tesseract_cmd": (
                ocr["tesseract_cmd"].strip()
                if isinstance(ocr.get("tesseract_cmd"), str)
                else ""
            ),
            "region": {
                "x": cls._bounded_number(
                    ocr_region.get("x"), OCR_DEFAULT_REGION["x"], -10000, 10000, True
                ),
                "y": cls._bounded_number(
                    ocr_region.get("y"), OCR_DEFAULT_REGION["y"], -10000, 10000, True
                ),
                "width": cls._bounded_number(
                    ocr_region.get("width"), OCR_DEFAULT_REGION["width"], 1, 10000, True
                ),
                "height": cls._bounded_number(
                    ocr_region.get("height"), OCR_DEFAULT_REGION["height"], 1, 10000, True
                ),
            },
        }
        merged["door_cooldowns"] = door_cooldowns
        merged["route_path"] = str(data.get("route_path", "") or "")
        language = str(data.get("language", "RU") or "RU").upper()
        merged["language"] = language if language in {"RU", "ENG"} else "RU"
        merged["bag_slot"] = cls._bounded_number(
            data.get("bag_slot"), cls.DEFAULTS["bag_slot"], 1, 9, True
        )
        merged["startup_delay"] = cls._bounded_number(
            data.get("startup_delay"), cls.DEFAULTS["startup_delay"], 0.0, 10.0
        )
        merged["playback_speed"] = cls._bounded_number(
            data.get("playback_speed"), cls.DEFAULTS["playback_speed"], 0.5, 2.0
        )
        merged["repeat_delay"] = cls._bounded_number(
            data.get("repeat_delay"), cls.DEFAULTS["repeat_delay"], 0.0, 600.0
        )
        merged["door_retry_interval"] = cls._bounded_number(
            data.get("door_retry_interval"),
            cls.DEFAULTS["door_retry_interval"],
            5.0,
            60.0,
        )
        saved_door_press_limit = data.get(
            "door_e_press_limit",
            data.get("door_retry_batch_size"),
        )
        if saved_door_press_limit == 3:
            saved_door_press_limit = 5
        merged["door_e_press_limit"] = cls._bounded_number(
            saved_door_press_limit,
            cls.DEFAULTS["door_e_press_limit"],
            1,
            5,
            True,
        )
        merged["ocr_scan_interval"] = cls._bounded_number(
            data.get("ocr_scan_interval"),
            cls.DEFAULTS["ocr_scan_interval"],
            0.1,
            30.0,
        )
        merged["ocr_frame_interval"] = cls._bounded_number(
            data.get("ocr_frame_interval"),
            cls.DEFAULTS["ocr_frame_interval"],
            0.0,
            2.0,
        )
        merged["mouse_gain"] = cls._bounded_number(
            data.get("mouse_gain"), cls.DEFAULTS["mouse_gain"], 0.05, 2.0
        )
        return merged

    @staticmethod
    def _bounded_number(value, default, minimum, maximum, integer=False):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return default
        if not math.isfinite(number):
            return default
        number = min(maximum, max(minimum, number))
        return int(number) if integer else number