import unittest
import time
from unittest.mock import patch

from pynput import keyboard

from app.input.recorder import InputRecorder
from app.route.route_manager import RouteManager


class InputRecorderTests(unittest.TestCase):
    def test_recording_pause_restores_saved_cursor_position(self):
        recorder = InputRecorder()
        recorder._started_at = time.monotonic()
        saved_position = {"x": 300, "y": 210}

        with patch("app.input.recorder.get_cursor_position", return_value=saved_position):
            with patch("app.input.recorder.set_cursor_position") as restore_cursor:
                recorder.pause()
                recorder.resume()

        restore_cursor.assert_called_once_with(saved_position)
        recorder._started_at = None

    def test_hotkey_is_ignored_and_pause_time_is_excluded(self):
        recorder = InputRecorder()
        recorder._started_at = 100.0
        recorder.set_ignored_hotkeys(["F9"])
        recorded = []
        recorder.action_recorded.connect(recorded.append)

        with patch(
            "app.input.recorder.time.monotonic",
            side_effect=[101.0, 102.0, 112.0, 113.0],
        ):
            recorder._on_key_down(keyboard.Key.f9)
            recorder._on_key_down(keyboard.KeyCode.from_char("w"))
            recorder.pause()
            recorder._on_key_up(keyboard.KeyCode.from_char("w"))
            recorder.resume()
            recorder._on_key_up(keyboard.KeyCode.from_char("w"))

        self.assertEqual([action["type"] for action in recorded], ["KEY_DOWN", "KEY_UP"])
        self.assertEqual([action["timestamp"] for action in recorded], [1.0, 3.0])
        recorder._started_at = None

    def test_keyboard_hook_repeat_does_not_duplicate_pressed_key_actions(self):
        recorder = InputRecorder()
        recorder._started_at = 1.0
        recorded = []
        recorder.action_recorded.connect(recorded.append)
        key = keyboard.KeyCode.from_char("w")

        with patch("app.input.recorder.time.monotonic", side_effect=[1.1, 1.2]):
            recorder._on_key_down(key)
            recorder._on_key_down(key)
            recorder._on_key_up(key)
            recorder._on_key_up(key)

        self.assertEqual(
            [action["type"] for action in recorded],
            ["KEY_DOWN", "KEY_UP"],
        )

    def test_hook_start_failure_cleans_up_unstarted_listeners(self):
        recorder = InputRecorder()
        errors = []
        recorder.error.connect(errors.append)
        with patch(
            "app.input.recorder.keyboard.Listener.start",
            side_effect=RuntimeError("hook unavailable"),
        ):
            recorder.start()

        self.assertFalse(recorder.recording)
        self.assertEqual(errors, ["hook unavailable"])

    def test_raw_mouse_delta_becomes_a_route_action(self):
        recorder = InputRecorder()
        recorder._started_at = 1.0
        manager = RouteManager()
        manager.start_recording()
        recorder.action_recorded.connect(manager.add_action)

        recorder.add_raw_mouse_delta(-8, 3)

        action = manager.route.actions[-1]
        self.assertEqual(action["type"], "MOUSE_MOVE")
        self.assertEqual((action["dx"], action["dy"]), (-8, 3))
        recorder._started_at = None
        manager.stop_recording()

    def test_fast_direction_reversal_is_recorded_as_separate_actions(self):
        recorder = InputRecorder()
        recorder._started_at = 1.0
        recorded = []
        recorder.action_recorded.connect(recorded.append)

        with patch("app.input.recorder.time.monotonic", side_effect=[1.001, 1.002, 1.003, 1.004]):
            recorder.add_raw_mouse_delta(40, 0)
            recorder.add_raw_mouse_delta(-40, 0)

        self.assertEqual(
            [(action["dx"], action["dy"]) for action in recorded],
            [(40, 0), (-40, 0)],
        )

    def test_special_keyboard_keys_are_recorded_on_both_edges(self):
        recorder = InputRecorder()
        recorder._started_at = time.monotonic()
        recorded = []
        recorder.action_recorded.connect(recorded.append)

        for key in (keyboard.Key.caps_lock, keyboard.Key.alt_gr, keyboard.Key.media_play_pause):
            recorder._on_key_down(key)
            recorder._on_key_up(key)

        self.assertEqual(
            [(action["type"], action["key"]) for action in recorded],
            [
                ("KEY_DOWN", "caps_lock"), ("KEY_UP", "caps_lock"),
                ("KEY_DOWN", "alt_gr"), ("KEY_UP", "alt_gr"),
                ("KEY_DOWN", "media_play_pause"), ("KEY_UP", "media_play_pause"),
            ],
        )

    def test_modifier_combination_preserves_key_order_and_virtual_key(self):
        recorder = InputRecorder()
        recorder._started_at = time.monotonic()
        recorded = []
        recorder.action_recorded.connect(recorded.append)

        for callback, key in (
            (recorder._on_key_down, keyboard.Key.shift_l),
            (recorder._on_key_down, keyboard.KeyCode.from_vk(65)),
            (recorder._on_key_up, keyboard.KeyCode.from_vk(65)),
            (recorder._on_key_up, keyboard.Key.shift_l),
        ):
            callback(key)

        self.assertEqual(
            [(action["type"], action["key"]) for action in recorded],
            [
                ("KEY_DOWN", "vk:160"),
                ("KEY_DOWN", "vk:65"),
                ("KEY_UP", "vk:65"),
                ("KEY_UP", "vk:160"),
            ],
        )

    def test_raw_keyboard_records_edges_suppresses_repeat_and_ignores_hotkey(self):
        recorder = InputRecorder()
        recorder._started_at = time.monotonic()
        recorder.set_ignored_hotkeys(["F10"])
        recorded = []
        recorder.action_recorded.connect(recorded.append)

        recorder.add_raw_keyboard_event(0x57, True)
        recorder.add_raw_keyboard_event(0x57, True)
        recorder.add_raw_keyboard_event(0x57, False)
        recorder.add_raw_keyboard_event(0x79, True)

        self.assertEqual(
            [(action["type"], action["key"]) for action in recorded],
            [("KEY_DOWN", "vk:87"), ("KEY_UP", "vk:87")],
        )

    def test_raw_keyboard_ignores_all_parts_of_configured_hotkey(self):
        recorder = InputRecorder()
        recorder._started_at = time.monotonic()
        recorder.set_ignored_hotkeys(["Ctrl+F6", "A"])
        recorded = []
        recorder.action_recorded.connect(recorded.append)

        for virtual_key in (0xA2, 0x75, 0x41):
            recorder.add_raw_keyboard_event(virtual_key, True)
            recorder.add_raw_keyboard_event(virtual_key, False)

        self.assertEqual(recorded, [])

    def test_raw_keyboard_capture_disables_duplicate_pynput_listener(self):
        recorder = InputRecorder()
        recorder.set_raw_keyboard_enabled(True)

        with patch("app.input.recorder.keyboard.Listener") as keyboard_listener, patch(
            "app.input.recorder.mouse.Listener"
        ) as mouse_listener:
            recorder.start()
            keyboard_listener.assert_not_called()
            mouse_listener.assert_called_once()
            recorder.stop()


if __name__ == "__main__":
    unittest.main()