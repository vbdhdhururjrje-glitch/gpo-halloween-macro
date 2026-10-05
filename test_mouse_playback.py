import ctypes
import time
import unittest
from unittest.mock import patch

from app.input import cursor
from app.input import relative_mouse as relative_mouse_module
from app.input.player import DOOR_INTERACTION_MAX_ATTEMPTS, PlaybackWorker
from app.route.route import Route
from app.route.route_point import RoutePoint


class MousePlaybackTests(unittest.TestCase):
    @patch("ctypes.windll.user32")
    def test_focus_does_not_remaximize_already_foreground_fullscreen_game(self, user32):
        user32.FindWindowW.return_value = 123
        user32.GetForegroundWindow.return_value = 123
        user32.IsZoomed.return_value = False

        self.assertTrue(cursor.focus_game_window())

        user32.ShowWindow.assert_not_called()

    @patch("ctypes.windll.user32")
    def test_focus_game_window_activates_window_before_input(self, user32):
        user32.FindWindowW.return_value = 123
        user32.GetForegroundWindow.side_effect = [0, 123]
        user32.IsZoomed.return_value = False

        cursor.focus_game_window()

        user32.ShowWindow.assert_called_with(123, 3)
        user32.SetForegroundWindow.assert_called_with(123)
        user32.SetActiveWindow.assert_called_with(123)
        user32.SwitchToThisWindow.assert_called_once_with(123, True)

    def test_relative_mouse_uses_send_input(self):
        with patch("ctypes.windll.user32.SendInput", return_value=1) as send_input:
            self.assertTrue(relative_mouse_module.send_relative_mouse(12, -8))
            count, events, size = send_input.call_args.args
            self.assertEqual(count, 1)
            self.assertEqual(size, ctypes.sizeof(relative_mouse_module.INPUT))
            self.assertEqual(events[0].mi.dx, 12)
            self.assertEqual(events[0].mi.dy, -8)
            self.assertEqual(events[0].mi.dwFlags, relative_mouse_module.MOUSEEVENTF_MOVE | relative_mouse_module.MOUSEEVENTF_MOVE_NOCOALESCE)

    def test_relative_mouse_button_uses_send_input(self):
        with patch("ctypes.windll.user32.SendInput", return_value=1) as send_input:
            self.assertTrue(relative_mouse_module.send_mouse_button("left", True))
            events = send_input.call_args.args[1]
            self.assertEqual(events[0].type, relative_mouse_module.INPUT_MOUSE)
            self.assertEqual(events[0].mi.dwFlags, relative_mouse_module.MOUSEEVENTF_LEFTDOWN)

    def test_keyboard_key_uses_scan_code_send_input(self):
        with patch("ctypes.windll.user32.VkKeyScanW", return_value=ord("W")), patch(
            "ctypes.windll.user32.MapVirtualKeyW", return_value=0x11
        ), patch(
            "ctypes.windll.user32.SendInput", return_value=1
        ) as send_input:
            self.assertTrue(relative_mouse_module.send_keyboard_key("w", True))
            events = send_input.call_args.args[1]
            self.assertEqual(events[0].type, relative_mouse_module.INPUT_KEYBOARD)
            self.assertEqual(events[0].ki.wVk, 0)
            self.assertEqual(events[0].ki.wScan, 0x11)
            self.assertEqual(events[0].ki.dwFlags, relative_mouse_module.KEYEVENTF_SCANCODE)

    def test_keyboard_special_keys_have_virtual_key_mappings(self):
        expected = {
            "caps_lock": 0x14,
            "alt_gr": 0xA5,
            "print_screen": 0x2C,
            "media_play_pause": 0xB3,
        }
        with patch("ctypes.windll.user32.MapVirtualKeyW", return_value=0), patch(
            "ctypes.windll.user32.SendInput", return_value=1
        ) as send_input:
            for key_name, virtual_key in expected.items():
                self.assertTrue(relative_mouse_module.send_keyboard_key(key_name, True))
                events = send_input.call_args.args[1]
                self.assertEqual(events[0].ki.wVk, virtual_key)

    def test_extended_keyboard_keys_set_extended_flag(self):
        with patch("ctypes.windll.user32.MapVirtualKeyW", return_value=0xE04B), patch(
            "ctypes.windll.user32.SendInput", return_value=1
        ) as send_input:
            self.assertTrue(relative_mouse_module.send_keyboard_key("left", True))
            events = send_input.call_args.args[1]

        self.assertEqual(events[0].ki.wScan, 0x4B)
        self.assertEqual(
            events[0].ki.dwFlags,
            relative_mouse_module.KEYEVENTF_SCANCODE | relative_mouse_module.KEYEVENTF_EXTENDEDKEY,
        )

    def test_relative_delta_is_subdivided_without_changing_total(self):
        worker = PlaybackWorker(Route(), 4, 0.0)
        worker._wait_active = lambda seconds: True

        with patch("app.input.player.send_relative_mouse") as send_relative:
            completed = worker._play_mouse_move(17, -5, 0.04)

        self.assertTrue(completed)
        self.assertEqual(sum(call.args[0] for call in send_relative.call_args_list), 17)
        self.assertEqual(sum(call.args[1] for call in send_relative.call_args_list), -5)
        self.assertGreater(len(send_relative.call_args_list), 1)

    def test_relative_delta_scales_to_current_resolution(self):
        route = Route(start={"screen_size": {"width": 1920, "height": 1080}})
        with patch("app.input.player.get_screen_size", return_value={"width": 960, "height": 540}):
            worker = PlaybackWorker(route, 4, 0.0, mouse_gain=1.0)
        worker._wait_active = lambda seconds: True

        with patch("app.input.player.send_relative_mouse") as send_relative:
            completed = worker._play_mouse_move(20, -10, 0.04)

        self.assertTrue(completed)
        self.assertEqual(sum(call.args[0] for call in send_relative.call_args_list), 10)
        self.assertEqual(sum(call.args[1] for call in send_relative.call_args_list), -5)

    def test_fast_large_delta_is_split_into_bounded_events(self):
        worker = PlaybackWorker(Route(), 4, 0.0, mouse_gain=1.0)
        worker._wait_active = lambda seconds: True

        with patch("app.input.player.send_relative_mouse") as send_relative:
            completed = worker._play_mouse_move(100, -65, 0.0)

        self.assertTrue(completed)
        self.assertEqual(sum(call.args[0] for call in send_relative.call_args_list), 100)
        self.assertEqual(sum(call.args[1] for call in send_relative.call_args_list), -65)
        self.assertTrue(all(
            max(abs(call.args[0]), abs(call.args[1])) <= 16
            for call in send_relative.call_args_list
        ))

    def test_high_rate_mouse_actions_keep_absolute_timing_without_focus_per_event(self):
        route = Route(actions=[
            {"type": "MOUSE_MOVE", "dx": 1, "dy": 0, "timestamp": 0.001},
            {"type": "MOUSE_MOVE", "dx": 1, "dy": 0, "timestamp": 0.002},
            {"type": "MOUSE_MOVE", "dx": 1, "dy": 0, "timestamp": 0.003},
        ])
        worker = PlaybackWorker(route, 4, 0.0)
        deadlines = []
        worker._wait_until = lambda deadline: deadlines.append(deadline) or True

        with patch("app.input.player.focus_game_window", return_value=True) as focus, patch(
            "app.input.player.send_keyboard_key", return_value=True
        ), patch("app.input.player.send_relative_mouse", return_value=True):
            worker.run()

        self.assertEqual(len(deadlines), 3)
        self.assertAlmostEqual(deadlines[1] - deadlines[0], 0.001, places=4)
        self.assertAlmostEqual(deadlines[2] - deadlines[1], 0.001, places=4)
        focus.assert_called_once()

    def test_late_input_does_not_compress_following_recorded_intervals(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "w", "timestamp": 0.1},
            {"type": "KEY_DOWN", "key": "a", "timestamp": 0.2},
        ])
        worker = PlaybackWorker(route, 4, 0.0)
        clock = [0.0]
        deadlines = []

        def wait_until(deadline):
            deadlines.append(deadline)
            clock[0] = max(clock[0], deadline)
            return True

        def perform(action):
            if action.get("type") == "KEY_DOWN" and action.get("key") == "w":
                clock[0] += 0.05

        worker._wait_until = wait_until

        with patch("app.input.player.time.monotonic", side_effect=lambda: clock[0]), patch(
            "app.input.player.focus_game_window", return_value=True
        ), patch("app.input.player.send_keyboard_key", return_value=True), patch.object(
            worker, "_perform", side_effect=perform
        ), patch("app.input.player.get_screen_size", return_value=None):
            worker.run()

        self.assertEqual(len(deadlines), 3)
        self.assertAlmostEqual(deadlines[1] - deadlines[0], 0.15, places=3)
        self.assertAlmostEqual(deadlines[2] - deadlines[1], 0.10, places=3)

    def test_recorded_e_key_events_are_not_skipped_by_external_cache(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "vk:69", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "vk:69", "timestamp": 0.01},
        ])
        worker = PlaybackWorker(route, 4, 0.0)
        worker._wait_until = lambda deadline: True

        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", return_value=True
        ) as send_key:
            worker.run()

        self.assertIn(("vk:69", True), [call.args for call in send_key.call_args_list])
        self.assertIn(("vk:69", False), [call.args for call in send_key.call_args_list])

    def test_playback_waits_for_ocr_confirmation_after_door_interaction(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "vk:69", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "vk:69", "timestamp": 0.01},
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.02},
        ])
        worker = PlaybackWorker(
            route,
            4,
            0.0,
            door_check_release_indices={1: (7, "vk:69")},
        )
        worker._wait_until = lambda deadline: True
        requested = []

        def confirm(door_id):
            requested.append(door_id)
            worker.resolve_door_check(True)

        worker.door_check_requested.connect(confirm)
        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", return_value=True
        ) as send_key:
            worker.run()

        self.assertEqual(requested, [7])
        self.assertIn(("w", True), [call.args for call in send_key.call_args_list])

    def test_playback_signals_door_approach_before_recorded_e_press(self):
        route = Route(
            points=[RoutePoint(id=7, type="DOOR", timestamp=0.0, action_index=0)],
            actions=[
                {"type": "KEY_DOWN", "key": "e", "timestamp": 0.0},
                {"type": "KEY_UP", "key": "e", "timestamp": 0.01},
                {"type": "KEY_DOWN", "key": "w", "timestamp": 0.02},
            ],
        )
        worker = PlaybackWorker(
            route,
            4,
            0.0,
            door_check_release_indices={1: (7, "e")},
            door_interaction_start_indices={0: 7},
        )
        worker._wait_until = lambda deadline: True
        order = []
        def start_ocr(door_id):
            order.append("ocr-start")
            worker.resolve_door_approach()

        worker.door_approached.connect(start_ocr)
        worker.door_check_requested.connect(
            lambda door_id: worker.resolve_door_check(True)
        )

        def send_key(key, pressed):
            if key == "e" and pressed:
                order.append("e-press")
            return True

        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", side_effect=send_key
        ):
            worker.run()

        self.assertLess(order.index("ocr-start"), order.index("e-press"))

    def test_ocr_door_wait_is_added_to_playback_timeline(self):
        worker = PlaybackWorker(Route(), 4, 0.0)
        monotonic_values = iter((100.0, 107.5))
        worker.door_check_requested.connect(
            lambda door_id: worker.resolve_door_check(True)
        )

        with patch("app.input.player.time.monotonic", side_effect=lambda: next(monotonic_values)):
            self.assertTrue(worker._wait_for_door_check(1, "vk:69"))

        self.assertEqual(worker._playback_pause_total, 7.5)

    def test_playback_stops_when_door_ocr_rejects_continuation(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "e", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "e", "timestamp": 0.01},
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.02},
        ])
        worker = PlaybackWorker(
            route,
            4,
            0.0,
            door_check_release_indices={1: (7, "vk:69")},
        )
        worker._wait_until = lambda deadline: True
        worker.door_check_requested.connect(lambda door_id: worker.resolve_door_check(False))

        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", return_value=True
        ) as send_key:
            worker.run()

        self.assertNotIn(("w", True), [call.args for call in send_key.call_args_list])

    def test_playback_retries_e_until_door_ocr_confirms_then_continues(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "vk:69", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "vk:69", "timestamp": 0.01},
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.02},
        ])
        worker = PlaybackWorker(
            route,
            4,
            0.0,
            door_check_release_indices={1: (7, "vk:69")},
        )
        worker._wait_until = lambda deadline: True
        requested = []

        def respond(door_id):
            requested.append(door_id)
            worker.resolve_door_check("retry" if len(requested) == 1 else True)

        worker.door_check_requested.connect(respond)
        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", return_value=True
        ) as send_key:
            worker.run()

        self.assertEqual(requested, [7, 7])
        self.assertEqual(
            [call.args for call in send_key.call_args_list].count(("vk:69", True)),
            2,
        )
        self.assertIn(("w", True), [call.args for call in send_key.call_args_list])

    def test_playback_keeps_retrying_after_ten_e_presses_until_confirmed(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "vk:69", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "vk:69", "timestamp": 0.01},
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.02},
        ])
        worker = PlaybackWorker(
            route,
            4,
            0.0,
            door_check_release_indices={1: (7, "vk:69")},
        )
        worker._wait_until = lambda deadline: True
        worker._wait_active = lambda seconds: True
        requested = []
        failures = []
        worker.failed.connect(failures.append)

        def reject(door_id):
            requested.append(door_id)
            worker.resolve_door_check(
                True
                if len(requested) == DOOR_INTERACTION_MAX_ATTEMPTS + 1
                else "retry"
            )

        worker.door_check_requested.connect(reject)
        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", return_value=True
        ) as send_key:
            worker.run()

        e_presses = [
            call for call in send_key.call_args_list
            if call.args == ("vk:69", True)
        ]
        self.assertEqual(len(requested), DOOR_INTERACTION_MAX_ATTEMPTS + 1)
        self.assertEqual(len(e_presses), DOOR_INTERACTION_MAX_ATTEMPTS + 1)
        self.assertIn(("w", True), [call.args for call in send_key.call_args_list])
        self.assertEqual(failures, [])

    def test_playback_continues_when_message_appears_on_tenth_e_check(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "vk:69", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "vk:69", "timestamp": 0.01},
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.02},
        ])
        worker = PlaybackWorker(
            route,
            4,
            0.0,
            door_check_release_indices={1: (7, "vk:69")},
        )
        worker._wait_until = lambda deadline: True
        worker._wait_active = lambda seconds: True
        requested = []

        def respond(door_id):
            requested.append(door_id)
            worker.resolve_door_check(
                True if len(requested) == DOOR_INTERACTION_MAX_ATTEMPTS else "retry"
            )

        worker.door_check_requested.connect(respond)
        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", return_value=True
        ) as send_key:
            worker.run()

        self.assertEqual(len(requested), DOOR_INTERACTION_MAX_ATTEMPTS)
        self.assertEqual(
            [call.args for call in send_key.call_args_list].count(("vk:69", True)),
            DOOR_INTERACTION_MAX_ATTEMPTS,
        )
        self.assertIn(("w", True), [call.args for call in send_key.call_args_list])

    def test_playback_does_not_repeat_bag_slot_recorded_in_route(self):
        route = Route(actions=[
            {"type": "KEY_DOWN", "key": "vk:49", "timestamp": 0.0},
            {"type": "KEY_UP", "key": "vk:49", "timestamp": 0.01},
            {"type": "KEY_DOWN", "key": "w", "timestamp": 0.02},
        ])
        worker = PlaybackWorker(route, 1, 0.0)
        worker._wait_until = lambda deadline: True

        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", return_value=True
        ) as send_key:
            worker.run()

        calls = [call.args for call in send_key.call_args_list]
        self.assertEqual(calls.count(("1", True)), 1)
        self.assertEqual(calls.count(("1", False)), 1)
        self.assertIn(("w", True), calls)

        def test_playback_speed_scales_recorded_action_timeline(self):
            route = Route(actions=[
                {"type": "KEY_DOWN", "key": "w", "timestamp": 0.0},
                {"type": "KEY_UP", "key": "w", "timestamp": 2.0},
            ])
            worker = PlaybackWorker(route, 4, 0.0, playback_speed=2.0)
            worker._wait_active = lambda seconds: True
            deadlines = []
            worker._wait_until = lambda deadline: deadlines.append(deadline) or True

            with patch("app.input.player.time.monotonic", return_value=100.0), patch(
                "app.input.player.focus_game_window", return_value=True
            ), patch("app.input.player.send_keyboard_key", return_value=True):
                worker.run()

            self.assertEqual(deadlines, [100.0, 101.0])
    def test_startup_releases_bag_slot_when_initial_key_up_fails(self):
        worker = PlaybackWorker(Route(), 1, 0.0)
        calls = []

        def send_key(key, pressed):
            calls.append((key, pressed))
            return len(calls) != 2

        with patch("app.input.player.focus_game_window", return_value=True), patch(
            "app.input.player.send_keyboard_key", side_effect=send_key
        ):
            worker.run()

        self.assertGreaterEqual(calls.count(("1", False)), 2)

    def test_mouse_gain_reduces_route_movement(self):
        worker = PlaybackWorker(Route(), 4, 0.0, mouse_gain=0.25)
        worker._wait_active = lambda seconds: True

        with patch("app.input.player.send_relative_mouse") as send_relative:
            completed = worker._play_mouse_move(20, -12, 0.04)

        self.assertTrue(completed)
        self.assertEqual(sum(call.args[0] for call in send_relative.call_args_list), 5)
        self.assertEqual(sum(call.args[1] for call in send_relative.call_args_list), -3)

    def test_mouse_move_uses_relative_sender(self):
        worker = PlaybackWorker(Route(), 4, 0.0)
        worker._wait_active = lambda seconds: True
        with patch("app.input.player.send_relative_mouse") as send_relative:
            worker._perform({"type": "MOUSE_MOVE", "dx": -12, "dy": 7})
        self.assertEqual(sum(call.args[0] for call in send_relative.call_args_list), -12)
        self.assertEqual(sum(call.args[1] for call in send_relative.call_args_list), 7)

    def test_mouse_move_uses_relative_delta_with_recorded_target(self):
        route = Route()
        route.start = {"cursor_position": {"x": 100, "y": 200}}
        worker = PlaybackWorker(route, 4, 0.0)
        worker._current_cursor_position = {"x": 100, "y": 200}
        worker._wait_active = lambda seconds: True

        with patch("app.input.player.send_relative_mouse") as send_relative:
            completed = worker._play_mouse_move(25, -10, 0.05)

        self.assertTrue(completed)
        self.assertEqual(sum(call.args[0] for call in send_relative.call_args_list), 25)
        self.assertEqual(sum(call.args[1] for call in send_relative.call_args_list), -10)

    def test_mouse_move_does_not_teleport_to_recorded_absolute_target(self):
        worker = PlaybackWorker(Route(), 4, 0.0)
        worker._current_cursor_position = {"x": 150, "y": 200}
        worker._wait_active = lambda seconds: True

        with patch("app.input.player.send_relative_mouse") as send_relative, patch(
            "app.input.player.set_cursor_position"
        ) as set_cursor:
            worker._perform({"type": "MOUSE_MOVE", "dx": 25, "dy": -10, "x": 175, "y": 190})

        self.assertEqual(sum(call.args[0] for call in send_relative.call_args_list), 25)
        self.assertEqual(sum(call.args[1] for call in send_relative.call_args_list), -10)
        set_cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()