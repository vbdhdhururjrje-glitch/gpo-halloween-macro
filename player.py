import threading
import time
import math

from PySide6.QtCore import QThread, Signal

from app.input.cursor import focus_game_window, get_cursor_position, get_screen_size, set_cursor_position
from app.input.relative_mouse import (
    send_keyboard_key,
    send_mouse_button,
    send_mouse_scroll,
    send_relative_mouse,
)


PLAYBACK_OVERRUN_TOLERANCE = 0.01
DOOR_INTERACTION_MAX_ATTEMPTS = 10


class PlaybackWorker(QThread):
    progress = Signal(int, int, str)
    action_changed = Signal(str)
    door_approached = Signal(int)
    failed = Signal(str)
    ended = Signal(bool)
    door_check_requested = Signal(int)

    def __init__(
        self,
        route,
        bag_slot,
        startup_delay,
        parent=None,
        mouse_gain=1.0,
        door_check_release_indices=None,
        door_interaction_start_indices=None,
        playback_speed=1.0,
    ):
        super().__init__(parent)
        self._actions = list(route.actions)
        self._points = list(route.points)
        self._bag_slot = str(bag_slot)
        self._startup_delay = float(startup_delay)
        self._mouse_gain = max(0.05, min(2.0, float(mouse_gain)))
        self._playback_speed = max(0.5, min(2.0, float(playback_speed)))
        self._door_check_release_indices = dict(door_check_release_indices or {})
        self._door_interaction_start_indices = dict(
            door_interaction_start_indices or {}
        )
        self._start_cursor_position = (
            route.start.get("cursor_position") if isinstance(route.start, dict) else None
        )
        self._mouse_scale_x = 1.0
        self._mouse_scale_y = 1.0
        self._mouse_scale_remainder_x = 0.0
        self._mouse_scale_remainder_y = 0.0
        recorded_screen = route.start.get("screen_size") if isinstance(route.start, dict) else None
        current_screen = get_screen_size()
        if isinstance(recorded_screen, dict) and current_screen:
            recorded_width = int(recorded_screen.get("width", 0) or 0)
            recorded_height = int(recorded_screen.get("height", 0) or 0)
            if recorded_width > 0 and recorded_height > 0:
                self._mouse_scale_x = current_screen["width"] / recorded_width * self._mouse_gain
                self._mouse_scale_y = current_screen["height"] / recorded_height * self._mouse_gain
        else:
            self._mouse_scale_x = self._mouse_gain
            self._mouse_scale_y = self._mouse_gain
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._held_keys = set()
        self._held_buttons = set()
        self._door_check_event = threading.Event()
        self._door_check_result = None
        self._door_approach_event = threading.Event()
        self._current_cursor_position = None
        self._playback_pause_total = 0.0

    def pause(self):
        self._pause_event.set()

    def resume(self):
        self._pause_event.clear()

    def stop(self):
        self._stop_event.set()
        self._door_check_event.set()
        self.release_all()

    def resolve_door_check(self, continue_route):
        self._door_check_result = continue_route
        self._door_check_event.set()

    def resolve_door_approach(self):
        self._door_approach_event.set()

    def _wait_for_door_approach(self, door_id):
        self._door_approach_event.clear()
        self.door_approached.emit(int(door_id))
        while not self._stop_event.is_set():
            if self._door_approach_event.wait(0.02):
                return True
        return False

    def _wait_for_door_check(self, door_id, interaction_key):
        wait_started = time.monotonic()
        while not self._stop_event.is_set():
            self._door_check_result = None
            self._door_check_event.clear()
            self.door_check_requested.emit(int(door_id))
            while not self._stop_event.is_set():
                if self._pause_event.is_set():
                    self._stop_event.wait(0.02)
                    continue
                if self._door_check_event.wait(0.02):
                    break
            if self._stop_event.is_set():
                return False
            if self._door_check_result is True:
                self._playback_pause_total += time.monotonic() - wait_started
                return True
            if self._door_check_result != "retry":
                return False
            self.action_changed.emit(f"RETRY E AT DOOR #{door_id}")
            if not focus_game_window():
                raise RuntimeError("Roblox lost focus before retrying door interaction")
            retry_key = interaction_key or "e"
            if not send_keyboard_key(retry_key, True):
                raise RuntimeError(f"Could not retry E interaction at DOOR #{door_id}")
            self._held_keys.add(retry_key)
            try:
                if not self._wait_active(0.05):
                    return False
            finally:
                if not send_keyboard_key(retry_key, False):
                    raise RuntimeError(f"Could not release retry E at DOOR #{door_id}")
                self._held_keys.discard(retry_key)
        return False

    def release_all(self):
        for key in tuple(self._held_keys):
            send_keyboard_key(key, False)
        self._held_keys.clear()
        for button in tuple(self._held_buttons):
            send_mouse_button(button, False)
        self._held_buttons.clear()
        for name in ("w", "a", "s", "d", "shift", "space"):
            send_keyboard_key(name, False)
    def _perform(self, action):
        action_type = action.get("type")
        if action_type == "KEY_DOWN":
            name = action["key"]
            if not send_keyboard_key(name, True):
                raise RuntimeError(f"Could not send keyboard press for {name}")
            self._held_keys.add(name)
        elif action_type == "KEY_UP":
            name = action["key"]
            if not send_keyboard_key(name, False):
                raise RuntimeError(f"Could not send keyboard release for {name}")
            self._held_keys.discard(name)
        elif action_type == "MOUSE_MOVE":
            dx = int(action.get("dx", 0))
            dy = int(action.get("dy", 0))
            target_x = action.get("x")
            target_y = action.get("y")
            target = (
                {"x": int(target_x), "y": int(target_y)}
                if target_x is not None and target_y is not None
                else None
            )
            duration = float(action.get("duration", 0.0) or 0.0)
            if not self._play_mouse_move(dx, dy, duration, target=target):
                raise RuntimeError("Could not send relative mouse movement")
        elif action_type == "MOUSE_SCROLL":
            if not send_mouse_scroll(int(action["dx"]), int(action["dy"])):
                raise RuntimeError("Could not send mouse scroll")
        elif action_type == "MOUSE_BUTTON_DOWN":
            if not focus_game_window():
                raise RuntimeError("Roblox is not in the foreground; activate its window and retry")
            name = action["button"]
            if send_mouse_button(name, True):
                self._held_buttons.add(name)
                return
            raise RuntimeError(f"Could not send mouse press for {name}")
        elif action_type == "MOUSE_BUTTON_UP":
            if not focus_game_window():
                raise RuntimeError("Roblox is not in the foreground; activate its window and retry")
            name = action["button"]
            hold_duration = float(action.get("hold_duration", 0.0) or 0.0)
            if hold_duration > 0:
                self._wait_active(hold_duration)
            if send_mouse_button(name, False):
                self._held_buttons.discard(name)
                return
            raise RuntimeError(f"Could not send mouse release for {name}")

    @staticmethod
    def _describe_action(action):
        action_type = action.get("type", "UNKNOWN")
        if action_type in {"KEY_DOWN", "KEY_UP"}:
            verb = "PRESS" if action_type == "KEY_DOWN" else "RELEASE"
            return f"{verb} {action.get('key', '?')}"
        if action_type == "MOUSE_MOVE":
            return f"MOUSE MOVE dx={action.get('dx', 0)} dy={action.get('dy', 0)}"
        if action_type == "MOUSE_SCROLL":
            return f"MOUSE SCROLL dx={action.get('dx', 0)} dy={action.get('dy', 0)}"
        if action_type.startswith("MOUSE_BUTTON_"):
            verb = "PRESS" if action_type.endswith("DOWN") else "RELEASE"
            return f"{verb} MOUSE {action.get('button', '?')}"
        return action_type

    def _is_configured_bag_slot_action(self, action):
        if action.get("type") not in {"KEY_DOWN", "KEY_UP"}:
            return False
        slot = self._bag_slot.lower()
        key = str(action.get("key", "")).lower()
        aliases = {slot}
        if len(slot) == 1:
            aliases.add(f"vk:{ord(slot.upper())}")
        return key in aliases

    def _emit_point_progress(self, point_index):
        point = self._points[point_index]
        self.progress.emit(
            point_index + 1,
            len(self._points),
            f"{point.type} #{point.id}",
        )
    def _restore_start_cursor(self):
        if self._start_cursor_position is None:
            self._current_cursor_position = None
            return
        try:
            set_cursor_position(self._start_cursor_position)
            self._current_cursor_position = dict(self._start_cursor_position)
        except Exception as exc:
            self.failed.emit(f"Could not restore start cursor position: {exc}")
            self._current_cursor_position = None

    def _play_mouse_move(self, dx, dy, duration, target=None, start_deadline=None):
        exact_x = int(dx) * self._mouse_scale_x + self._mouse_scale_remainder_x
        exact_y = int(dy) * self._mouse_scale_y + self._mouse_scale_remainder_y
        scaled_dx = math.floor(exact_x + 0.5) if exact_x >= 0 else math.ceil(exact_x - 0.5)
        scaled_dy = math.floor(exact_y + 0.5) if exact_y >= 0 else math.ceil(exact_y - 0.5)
        self._mouse_scale_remainder_x = exact_x - scaled_dx
        self._mouse_scale_remainder_y = exact_y - scaled_dy
        duration = max(0.0, duration)
        time_steps = math.ceil(duration / 0.008)
        distance_steps = math.ceil(max(abs(scaled_dx), abs(scaled_dy)) / 16)
        steps = max(1, min(64, max(time_steps, distance_steps)))
        sent_x = 0
        sent_y = 0
        pause_total_at_start = self._playback_pause_total
        for step_index in range(1, steps + 1):
            if duration > 0:
                if start_deadline is None:
                    if not self._wait_active(duration / steps):
                        return False
                elif not self._wait_until(
                    start_deadline
                    + self._playback_pause_total
                    - pause_total_at_start
                    + duration * step_index / steps
                ):
                    return False
            target_x = round(scaled_dx * step_index / steps)
            target_y = round(scaled_dy * step_index / steps)
            step_x = target_x - sent_x
            step_y = target_y - sent_y
            if (step_x or step_y) and not send_relative_mouse(step_x, step_y):
                return False
            sent_x = target_x
            sent_y = target_y

        if target is not None:
            self._current_cursor_position = target
        elif self._current_cursor_position is not None:
            self._current_cursor_position = {
                "x": int(self._current_cursor_position["x"] + scaled_dx),
                "y": int(self._current_cursor_position["y"] + scaled_dy),
            }
        return True

    def _wait_active(self, seconds):
        remaining = max(0.0, seconds)
        last_tick = time.monotonic()
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                self._stop_event.wait(0.02)
                last_tick = time.monotonic()
                continue
            if remaining <= 0:
                return True
            now = time.monotonic()
            remaining -= now - last_tick
            last_tick = now
            self._stop_event.wait(min(0.02, max(0.0, remaining)))
        return not self._stop_event.is_set()

    def _wait_until(self, deadline):
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                paused_at = time.monotonic()
                while self._pause_event.is_set() and not self._stop_event.is_set():
                    self._stop_event.wait(0.02)
                pause_duration = time.monotonic() - paused_at
                self._playback_pause_total += pause_duration
                deadline += pause_duration
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self._stop_event.wait(min(0.005, remaining))
        return False

    def run(self):
        completed = False
        try:
            if not focus_game_window():
                raise RuntimeError("Could not activate the Roblox window")
            self._restore_start_cursor()
            if not send_keyboard_key(self._bag_slot, True):
                raise RuntimeError(f"Could not select bag slot {self._bag_slot}")
            self._held_keys.add(self._bag_slot)
            if not send_keyboard_key(self._bag_slot, False):
                raise RuntimeError(f"Could not release bag slot {self._bag_slot}")
            self._held_keys.discard(self._bag_slot)
            if not self._wait_active(self._startup_delay):
                return

            playback_origin = time.monotonic()
            self._playback_pause_total = 0.0
            last_focus_check = playback_origin
            previous_timestamp = 0.0
            point_index = 0
            while (point_index < len(self._points)
                   and self._points[point_index].action_index == 0):
                self._emit_point_progress(point_index)
                point_index += 1
            for action_index, action in enumerate(self._actions):
                timestamp = max(previous_timestamp, float(action.get("timestamp", 0.0)))
                interval = timestamp - previous_timestamp
                is_mouse_move = action.get("type") == "MOUSE_MOVE"
                duration = 0.0
                action_start_timestamp = timestamp
                if is_mouse_move and "duration" in action:
                    duration = float(action["duration"])
                    duration = min(max(0.0, duration), interval)
                    action_start_timestamp = timestamp - duration
                    duration /= self._playback_speed
                action_deadline = (
                    playback_origin
                    + action_start_timestamp / self._playback_speed
                    + self._playback_pause_total
                )
                if not self._wait_until(action_deadline):
                    return
                if self._is_configured_bag_slot_action(action):
                    self.action_changed.emit(
                        f"SKIP BAG SLOT {self._bag_slot} (selected at startup)"
                    )
                    previous_timestamp = timestamp
                    while (point_index < len(self._points)
                           and self._points[point_index].action_index <= action_index + 1):
                        self._emit_point_progress(point_index)
                        point_index += 1
                    continue
                door_id = self._door_interaction_start_indices.get(action_index)
                if door_id is not None and not self._wait_for_door_approach(door_id):
                    return
                action_type = action.get("type")
                if is_mouse_move:
                    now = time.monotonic()
                    if now - last_focus_check >= 0.1:
                        if not focus_game_window():
                            raise RuntimeError("Roblox is not in the foreground; playback stopped")
                        last_focus_check = now
                elif action_type not in {"MOUSE_BUTTON_DOWN", "MOUSE_BUTTON_UP"}:
                    if not focus_game_window():
                        raise RuntimeError("Roblox is not in the foreground; playback stopped")
                    last_focus_check = time.monotonic()
                self.action_changed.emit(self._describe_action(action))
                if is_mouse_move:
                    target = None
                    if "x" in action and "y" in action:
                        target = {"x": int(action["x"]), "y": int(action["y"])}
                    if not self._play_mouse_move(
                        int(action["dx"]),
                        int(action["dy"]),
                        duration,
                        target=target,
                        start_deadline=action_deadline,
                    ):
                        return
                else:
                    self._perform(action)
                previous_timestamp = timestamp
                while (point_index < len(self._points)
                       and self._points[point_index].action_index <= action_index + 1):
                    self._emit_point_progress(point_index)
                    point_index += 1
                door_check = self._door_check_release_indices.get(action_index)
                if door_check is not None:
                    door_id, interaction_key = door_check
                    if not self._wait_for_door_check(door_id, interaction_key):
                        if not self._stop_event.is_set():
                            self.failed.emit(
                                f"DOOR #{door_id} was not confirmed by OCR; playback stopped"
                            )
                            self.stop()
                        return
                scheduled_end = (
                    playback_origin
                    + timestamp / self._playback_speed
                    + self._playback_pause_total
                )
                overrun = time.monotonic() - scheduled_end
                if overrun > PLAYBACK_OVERRUN_TOLERANCE:
                    playback_origin += overrun
            while point_index < len(self._points):
                self._emit_point_progress(point_index)
                point_index += 1
            if not self._wait_active(0):
                return
            completed = True
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.release_all()
            self.ended.emit(completed and not self._stop_event.is_set())