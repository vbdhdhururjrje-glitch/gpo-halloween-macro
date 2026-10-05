import ctypes
import time
from ctypes import wintypes


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def focus_game_window():
    try:
        user32 = ctypes.windll.user32
        for title in ("Roblox", "RobloxPlayerBeta", "RobloxPlayer"):
            hwnd = user32.FindWindowW(None, title)
            if hwnd:
                if user32.GetForegroundWindow() == hwnd:
                    return True
                try:
                    user32.AllowSetForegroundWindow(ctypes.windll.kernel32.GetCurrentProcessId())
                except Exception:
                    pass
                user32.ShowWindow(hwnd, 3)
                if hasattr(user32, "BringWindowToTop"):
                    user32.BringWindowToTop(hwnd)
                if hasattr(user32, "SwitchToThisWindow"):
                    user32.SwitchToThisWindow(hwnd, True)
                user32.SetForegroundWindow(hwnd)
                user32.SetActiveWindow(hwnd)
                deadline = time.monotonic() + 0.5
                while time.monotonic() < deadline:
                    if user32.GetForegroundWindow() == hwnd:
                        return True
                    time.sleep(0.01)
                return user32.GetForegroundWindow() == hwnd
    except Exception:
        pass
    return False


def get_cursor_position():
    try:
        point = POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return None
        return {"x": int(point.x), "y": int(point.y)}
    except Exception:
        return None


def get_screen_size():
    try:
        user32 = ctypes.windll.user32
        width = int(user32.GetSystemMetrics(0))
        height = int(user32.GetSystemMetrics(1))
        if width > 0 and height > 0:
            return {"width": width, "height": height}
    except Exception:
        pass
    return None


def set_cursor_position(position):
    if not isinstance(position, dict) or "x" not in position or "y" not in position:
        return False
    x = int(position["x"])
    y = int(position["y"])
    try:
        return bool(ctypes.windll.user32.SetCursorPos(x, y))
    except Exception:
        return False