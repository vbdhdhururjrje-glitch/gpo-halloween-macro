from pynput import keyboard
from PySide6.QtCore import QObject, Signal


class HotkeyManager(QObject):
    pressed = Signal(str)
    error = Signal(str)

    @staticmethod
    def _to_pynput(shortcut):
        parts = [part.strip().lower() for part in shortcut.split("+") if part.strip()]
        if not parts:
            raise ValueError("Hotkey cannot be empty.")
        return "+".join(
            part if part.startswith("<") and part.endswith(">")
            else f"<{part}>" if len(part) > 1 else part
            for part in parts
        )

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None

    def start(self, shortcuts):
        self.stop()
        bindings = {}
        try:
            for action, shortcut in shortcuts.items():
                bindings[self._to_pynput(shortcut)] = (
                    lambda name=action: self.pressed.emit(name)
                )
            self._listener = keyboard.GlobalHotKeys(bindings)
            self._listener.start()
        except Exception as exc:
            self.stop()
            self.error.emit(str(exc))

    def stop(self):
        if self._listener is not None:
            try:
                self._listener.stop()
                if self._listener.is_alive():
                    self._listener.join(timeout=0.5)
            except RuntimeError:
                pass
            self._listener = None