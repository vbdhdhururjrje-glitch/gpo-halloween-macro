import time
import unittest
from unittest.mock import patch

from pynput import mouse

from app.input.player import PlaybackWorker
from app.input.recorder import InputRecorder
from app.route.route import Route
from app.route.route_manager import RouteManager


class MouseClickTests(unittest.TestCase):
    def test_recorder_captures_left_and_right_button_edges(self):
        recorder = InputRecorder()
        recorder._started_at = time.monotonic()
        manager = RouteManager()
        manager.start_recording()
        recorder.action_recorded.connect(manager.add_action)

        for button in (mouse.Button.left, mouse.Button.right):
            recorder._on_mouse_click(0, 0, button, True)
            recorder._on_mouse_click(0, 0, button, False)

        self.assertEqual(
            [(action["type"], action["button"]) for action in manager.route.actions],
            [
                ("MOUSE_BUTTON_DOWN", "left"),
                ("MOUSE_BUTTON_UP", "left"),
                ("MOUSE_BUTTON_DOWN", "right"),
                ("MOUSE_BUTTON_UP", "right"),
            ],
        )
        recorder._started_at = None
        manager.stop_recording()

    def test_player_replays_left_and_right_button_edges(self):
        worker = PlaybackWorker(Route(), 4, 0.0)

        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_mouse_button", return_value=True
        ) as send_mouse_button:
            for button in ("left", "right"):
                worker._perform({"type": "MOUSE_BUTTON_DOWN", "button": button})
                worker._perform({"type": "MOUSE_BUTTON_UP", "button": button})

        self.assertEqual(
            send_mouse_button.call_args_list,
            [
                (("left", True), {}),
                (("left", False), {}),
                (("right", True), {}),
                (("right", False), {}),
            ],
        )

    def test_player_uses_os_input_for_button_events(self):
        worker = PlaybackWorker(Route(), 4, 0.0)
        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_mouse_button"
        ) as send_mouse_button:
            worker._perform({"type": "MOUSE_BUTTON_DOWN", "button": "left"})
            worker._perform({"type": "MOUSE_BUTTON_UP", "button": "left", "hold_duration": 0.1})

        self.assertEqual(send_mouse_button.call_args_list, [
            (("left", True), {}),
            (("left", False), {}),
        ])

    def test_player_does_not_send_click_without_game_focus(self):
        worker = PlaybackWorker(Route(), 4, 0.0)
        with patch("app.input.player.focus_game_window", return_value=False), patch(
            "app.input.player.send_mouse_button"
        ) as send_mouse_button:
            with self.assertRaisesRegex(RuntimeError, "Roblox is not in the foreground"):
                worker._perform({"type": "MOUSE_BUTTON_DOWN", "button": "left"})

        send_mouse_button.assert_not_called()

    def test_player_holds_button_for_recorded_duration_before_release(self):
        worker = PlaybackWorker(Route(), 4, 0.0)
        waits = []
        worker._wait_active = lambda seconds: waits.append(seconds) or True

        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_mouse_button", return_value=True
        ):
            worker._perform({"type": "MOUSE_BUTTON_DOWN", "button": "left"})
            worker._perform({"type": "MOUSE_BUTTON_UP", "button": "left", "hold_duration": 0.42})

        self.assertEqual(waits, [0.42])


if __name__ == "__main__":
    unittest.main()