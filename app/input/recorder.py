import time

from pynput import keyboard, mouse
from PySide6.QtCore import QObject, Signal

from app.input.cursor import get_cursor_position, set_cursor_position

MODIFIER_VIRTUAL_KEYS = {
    "shift": (0xA0, 0xA1),
    "shift_l": (0xA0,),
    "shift_r": (0xA1,),
    "ctrl": (0xA2, 0xA3),
    "ctrl_l": (0xA2,),
    "ctrl_r": (0xA3,),
    "alt": (0xA4, 0xA5),
    "alt_l": (0xA4,),
    "alt_r": (0xA5,),
    "alt_gr": (0xA5,),
}


class InputRecorder(QObject):
    action_recorded = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keyboard_listener = None
        self._mouse_listener = None
        self._raw_keyboard_enabled = False
        self._raw_pressed_keys = set()
        self._started_at = None
        self._last_mouse_position = None
        self._button_press_times = {}
        self._ignored_keys = set()
        self._raw_mouse_enabled = False
        self._hook_pressed_keys = set()
        self._paused_hook_key_releases = []
        self._paused = False
        self._paused_at = None
        self._paused_total = 0.0
        self._pause_cursor_position = None

    def set_ignored_hotkeys(self, shortcuts):
        ignored = set()
        for shortcut in shortcuts:
            for part in shortcut.lower().replace("<", "").replace(">", "").split("+"):
                part = part.strip()
                if part.startswith("f") and part[1:].isdigit():
                    ignored.add(part)
                elif part in MODIFIER_VIRTUAL_KEYS:
                    ignored.update(
                        f"vk:{virtual_key}"
                        for virtual_key in MODIFIER_VIRTUAL_KEYS[part]
                    )
                elif len(part) == 1:
                    ignored.add(f"vk:{ord(part.upper())}")
                else:
                    key = getattr(keyboard.Key, part, None)
                    virtual_key = getattr(getattr(key, "value", None), "vk", None)
                    ignored.add(
                        f"vk:{virtual_key}" if virtual_key is not None else part
                    )
        self._ignored_keys = ignored

    @property
    def recording(self):
        return self._started_at is not None

    @property
    def paused(self):
        return self._paused

    def set_raw_mouse_enabled(self, enabled):
        self._raw_mouse_enabled = bool(enabled)

    def set_raw_keyboard_enabled(self, enabled):
        self._raw_keyboard_enabled = bool(enabled)

    def start(self):
        self.stop()
        self._pause_cursor_position = None
        self._started_at = time.monotonic()
        self._last_mouse_position = None
        self._button_press_times = {}
        self._hook_pressed_keys.clear()
        self._paused_hook_key_releases.clear()
        self._paused = False
        self._paused_at = None
        self._paused_total = 0.0
        try:
            if not self._raw_keyboard_enabled:
                self._keyboard_listener = keyboard.Listener(
                    on_press=self._on_key_down,
                    on_release=self._on_key_up,
                )
            mouse_callbacks = {
                "on_click": self._on_mouse_click,
                "on_scroll": self._on_mouse_scroll,
            }
            if not self._raw_mouse_enabled:
                mouse_callbacks["on_move"] = self._on_mouse_move
            self._mouse_listener = mouse.Listener(**mouse_callbacks)
            if self._keyboard_listener is not None:
                self._keyboard_listener.start()
            self._mouse_listener.start()
        except Exception as exc:
            self.stop()
            self.error.emit(str(exc))

    def stop(self):
        if self._started_at is None:
            return
        self._button_press_times.clear()
        self._hook_pressed_keys.clear()
        self._paused_hook_key_releases.clear()
        self._raw_pressed_keys.clear()
        self._started_at = None
        self._paused = False
        self._paused_at = None
        for listener in (self._keyboard_listener, self._mouse_listener):
            if listener is not None:
                try:
                    listener.stop()
                    if listener.is_alive():
                        listener.join(timeout=0.5)
                except RuntimeError:
                    pass
        self._keyboard_listener = None
        self._mouse_listener = None

    def pause(self):
        if self.recording and not self._paused:
            self._pause_cursor_position = get_cursor_position()
            self._paused_at = time.monotonic()
            self._paused = True

    def resume(self):
        if self.recording and self._paused:
            if self._pause_cursor_position is not None:
                try:
                    set_cursor_position(self._pause_cursor_position)
                except Exception as exc:
                    self.error.emit(f"Could not restore cursor position: {exc}")
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None
            self._paused = False
            for name in self._paused_hook_key_releases:
                self._emit({"type": "KEY_UP", "key": name})
            self._paused_hook_key_releases.clear()
            self._last_mouse_position = None
            self._pause_cursor_position = None

    def _emit(self, action):
        if self._started_at is not None and not self._paused:
            action["timestamp"] = round(
                time.monotonic() - self._started_at - self._paused_total, 6
            )
            self.action_recorded.emit(action)

    @staticmethod
    def _key_name(key):
        if isinstance(key, keyboard.KeyCode):
            if key.vk is not None:
                return f"vk:{key.vk}"
            if key.char is not None:
                return key.char
            return "unknown"
        if key.name in {"shift", "shift_l", "shift_r", "ctrl", "ctrl_l", "ctrl_r", "alt", "alt_l", "alt_r"}:
            virtual_key = getattr(key.value, "vk", None)
            if virtual_key is not None:
                return f"vk:{virtual_key}"
        return key.name

    def _on_key_down(self, key):
        name = self._key_name(key)
        if (
            self._paused
            or name.lower() in self._ignored_keys
            or name in self._hook_pressed_keys
        ):
            return
        self._hook_pressed_keys.add(name)
        self._emit({"type": "KEY_DOWN", "key": name})

    def _on_key_up(self, key):
        name = self._key_name(key)
        if name.lower() in self._ignored_keys or name not in self._hook_pressed_keys:
            return
        self._hook_pressed_keys.remove(name)
        if self._paused:
            self._paused_hook_key_releases.append(name)
            return
        self._emit({"type": "KEY_UP", "key": name})

    def _on_mouse_move(self, x, y):
        if self._paused:
            self._last_mouse_position = (x, y)
            return
        if self._last_mouse_position is None:
            self._last_mouse_position = (x, y)
            return
        previous_x, previous_y = self._last_mouse_position
        self.add_raw_mouse_delta(x - previous_x, y - previous_y)
        self._last_mouse_position = (x, y)

    def add_raw_mouse_delta(self, dx, dy):
        if not self.recording or self._paused:
            return
        self._emit({
            "type": "MOUSE_MOVE",
            "dx": int(dx),
            "dy": int(dy),
        })

    def add_raw_keyboard_event(self, virtual_key, pressed):
        if not self.recording or self._paused:
            return
        virtual_key = int(virtual_key)
        if 0x70 <= virtual_key <= 0x87:
            name = f"f{virtual_key - 0x6F}"
        else:
            name = f"vk:{virtual_key}"
        if name in self._ignored_keys:
            return
        if pressed:
            if virtual_key in self._raw_pressed_keys:
                return
            self._raw_pressed_keys.add(virtual_key)
            action_type = "KEY_DOWN"
        else:
            self._raw_pressed_keys.discard(virtual_key)
            action_type = "KEY_UP"
        self._emit({"type": action_type, "key": name})

    def _on_mouse_click(self, x, y, button, pressed):
        button_name = button.name
        if pressed:
            self._button_press_times[button_name] = time.monotonic()
            self._emit({
                "type": "MOUSE_BUTTON_DOWN",
                "button": button_name,
            })
            return

        press_started = self._button_press_times.pop(button_name, None)
        hold_duration = 0.0
        if press_started is not None:
            hold_duration = max(0.0, time.monotonic() - press_started)
        self._emit({
            "type": "MOUSE_BUTTON_UP",
            "button": button_name,
            "hold_duration": round(hold_duration, 3),
        })

    def _on_mouse_scroll(self, x, y, dx, dy):
        self._emit({"type": "MOUSE_SCROLL", "dx": dx, "dy": dy})