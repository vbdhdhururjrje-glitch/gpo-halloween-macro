import unittest

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.config.config_manager import ConfigManager, OCR_DEFAULT_REGION
from app.gui.main_window import HotkeyCaptureEdit
from app.input.hotkeys import HotkeyManager


class HotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_older_settings_receive_default_record_hotkey(self):
        settings = ConfigManager._merge_defaults({"hotkeys": {"start": "F5"}})
        self.assertEqual(settings["hotkeys"]["start"], "F5")
        self.assertEqual(settings["hotkeys"]["record"], "F10")
        self.assertEqual(settings["mouse_gain"], 1.0)
        self.assertEqual(settings["repeat_delay"], 5.0)
        self.assertEqual(settings["door_retry_interval"], 5.0)
        self.assertEqual(settings["playback_speed"], 1.0)
        self.assertEqual(settings["ocr_scan_interval"], 0.5)
        self.assertEqual(settings["door_e_press_limit"], 5)
        self.assertEqual(settings["ocr_frame_interval"], 0.05)
        self.assertEqual(settings["route_path"], "")
        self.assertEqual(settings["ocr"]["region"], OCR_DEFAULT_REGION)

    def test_mouse_gain_is_clamped_to_supported_range(self):
        settings = ConfigManager._merge_defaults({"mouse_gain": 10})
        self.assertEqual(settings["mouse_gain"], 2.0)

    def test_invalid_persisted_values_fall_back_to_safe_defaults(self):
        settings = ConfigManager._merge_defaults({
            "bag_slot": "invalid",
            "startup_delay": "invalid",
            "playback_speed": "invalid",
            "repeat_delay": "invalid",
            "door_retry_interval": "invalid",
            "ocr_scan_interval": "invalid",
            "door_e_press_limit": "invalid",
            "ocr_frame_interval": "invalid",
            "mouse_gain": "invalid",
            "hotkeys": {"start": None},
            "ocr": {"region": None, "tesseract_cmd": None},
        })

        self.assertEqual(settings["bag_slot"], 4)
        self.assertEqual(settings["startup_delay"], 1.0)
        self.assertEqual(settings["playback_speed"], 1.0)
        self.assertEqual(settings["repeat_delay"], 5.0)
        self.assertEqual(settings["door_retry_interval"], 5.0)
        self.assertEqual(settings["ocr_scan_interval"], 0.5)
        self.assertEqual(settings["door_e_press_limit"], 5)
        self.assertEqual(settings["ocr_frame_interval"], 0.05)
        self.assertNotIn("respawn_delay", settings)
        self.assertNotIn("recovery_key_interval", settings)
        self.assertNotIn("checkpoint_threshold", settings)
        self.assertEqual(settings["mouse_gain"], 1.0)
        self.assertEqual(settings["hotkeys"]["start"], "F6")
        self.assertEqual(settings["ocr"]["tesseract_cmd"], "")
        self.assertEqual(
            settings["ocr"]["region"],
            ConfigManager.DEFAULTS["ocr"]["region"],
        )

    def test_previous_door_retry_batch_setting_migrates_to_press_limit(self):
        settings = ConfigManager._merge_defaults({"door_retry_batch_size": 6})

        self.assertEqual(settings["door_e_press_limit"], 5)

    def test_previous_maximum_door_press_limit_migrates_to_five(self):
        settings = ConfigManager._merge_defaults({"door_e_press_limit": 3})

        self.assertEqual(settings["door_e_press_limit"], 5)

    def test_door_retry_interval_is_at_least_five_seconds(self):
        settings = ConfigManager._merge_defaults({"door_retry_interval": 2.0})

        self.assertEqual(settings["door_retry_interval"], 5.0)

    def test_language_defaults_to_russian_and_rejects_unknown_values(self):
        self.assertEqual(ConfigManager._merge_defaults({})["language"], "RU")
        self.assertEqual(
            ConfigManager._merge_defaults({"language": "fr"})["language"],
            "RU",
        )
        self.assertEqual(
            ConfigManager._merge_defaults({"language": "eng"})["language"],
            "ENG",
        )

    def test_record_hotkey_uses_global_hotkey_syntax(self):
        self.assertEqual(HotkeyManager._to_pynput("F10"), "<f10>")

    def test_hotkey_field_captures_pressed_key(self):
        field = HotkeyCaptureEdit()
        field.show()
        field.setFocus()

        QTest.keyClick(field, Qt.Key_F8)

        self.assertEqual(
            field.keySequence().toString(QKeySequence.SequenceFormat.PortableText),
            "F8",
        )
        field.close()


if __name__ == "__main__":
    unittest.main()