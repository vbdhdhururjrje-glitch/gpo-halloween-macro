import ctypes
import sys
from ctypes import wintypes


MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_MOVE_NOCOALESCE = 0x2000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC_EX = 4
BUTTON_EVENT_MAP = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}
KEY_NAME_TO_VK = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "shift_l": 0xA0,
    "shift_r": 0xA1,
    "ctrl": 0x11,
    "ctrl_l": 0xA2,
    "ctrl_r": 0xA3,
    "alt": 0x12,
    "alt_l": 0xA4,
    "alt_r": 0xA5,
    "alt_gr": 0xA5,
    "caps_lock": 0x14,
    "esc": 0x1B,
    "space": 0x20,
    "page_up": 0x21,
    "page_down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "cmd": 0x5B,
    "cmd_l": 0x5B,
    "cmd_r": 0x5C,
    "menu": 0x5D,
    "num_lock": 0x90,
    "scroll_lock": 0x91,
    "pause": 0x13,
    "print_screen": 0x2C,
    "media_previous": 0xB1,
    "media_next": 0xB0,
    "media_play_pause": 0xB3,
    "media_stop": 0xB2,
    "media_volume_mute": 0xAD,
    "media_volume_down": 0xAE,
    "media_volume_up": 0xAF,
}
EXTENDED_VIRTUAL_KEYS = {
    0x21, 0x22, 0x23, 0x24,
    0x25, 0x26, 0x27, 0x28,
    0x2D, 0x2E,
    0x5B, 0x5C, 0x5D,
    0xA3, 0xA5,
    0xB0, 0xB1, 0xB2, 0xB3, 0xAD, 0xAE, 0xAF,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouse_data", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", _INPUTUNION)]


def _send_input_event(flags, dx=0, dy=0, data=0):
    if sys.platform != "win32":
        return False

    event = INPUT()
    event.type = INPUT_MOUSE
    event.mi = MOUSEINPUT(int(dx), int(dy), int(data) & 0xFFFFFFFF, flags, 0, 0)
    events = (INPUT * 1)(event)
    send_input = ctypes.windll.user32.SendInput
    send_input.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    send_input.restype = wintypes.UINT
    return send_input(1, events, ctypes.sizeof(INPUT)) == 1


def _send_keyboard_event(virtual_key, pressed):
    if sys.platform != "win32":
        return False

    map_virtual_key = ctypes.windll.user32.MapVirtualKeyW
    map_virtual_key.argtypes = [wintypes.UINT, wintypes.UINT]
    map_virtual_key.restype = wintypes.UINT
    mapped_scan = int(map_virtual_key(int(virtual_key), MAPVK_VK_TO_VSC_EX))
    scan_code = mapped_scan & 0xFF
    use_scan_code = scan_code != 0
    is_extended = (
        mapped_scan >> 8 in (0xE0, 0xE1)
        or int(virtual_key) in EXTENDED_VIRTUAL_KEYS
    )
    flags = KEYEVENTF_SCANCODE if use_scan_code else 0
    if is_extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if not pressed:
        flags |= KEYEVENTF_KEYUP

    event = INPUT()
    event.type = INPUT_KEYBOARD
    event.ki = KEYBDINPUT(
        0 if use_scan_code else int(virtual_key),
        scan_code if use_scan_code else 0,
        flags,
        0,
        0,
    )
    events = (INPUT * 1)(event)
    send_input = ctypes.windll.user32.SendInput
    send_input.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    send_input.restype = wintypes.UINT
    return send_input(1, events, ctypes.sizeof(INPUT)) == 1


def send_keyboard_key(key_name, pressed):
    key_name = str(key_name)
    lowered_name = key_name.lower()
    if lowered_name.startswith("vk:"):
        virtual_key = int(lowered_name.split(":", 1)[1])
    elif lowered_name in KEY_NAME_TO_VK:
        virtual_key = KEY_NAME_TO_VK[lowered_name]
    elif len(key_name) == 1 and sys.platform == "win32":
        vk_key_scan = ctypes.windll.user32.VkKeyScanW
        vk_key_scan.argtypes = [wintypes.WCHAR]
        vk_key_scan.restype = ctypes.c_short
        mapped_key = vk_key_scan(key_name)
        if mapped_key == -1:
            return False
        virtual_key = mapped_key & 0xFF
    elif lowered_name.startswith("f") and lowered_name[1:].isdigit():
        function_number = int(lowered_name[1:])
        if not 1 <= function_number <= 24:
            return False
        virtual_key = 0x70 + function_number - 1
    else:
        return False
    return _send_keyboard_event(virtual_key, pressed)


def send_relative_mouse(dx, dy):
    return _send_input_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_MOVE_NOCOALESCE, dx, dy)


def send_mouse_button(button_name, pressed):
    if sys.platform != "win32":
        return False

    button_key = str(button_name).lower()
    if button_key not in BUTTON_EVENT_MAP:
        return False

    down_flag, up_flag = BUTTON_EVENT_MAP[button_key]
    flags = down_flag if pressed else up_flag
    return _send_input_event(flags)


def send_mouse_scroll(dx, dy):
    if sys.platform != "win32":
        return False
    sent = True
    if dy:
        sent = _send_input_event(MOUSEEVENTF_WHEEL, data=int(dy) * 120) and sent
    if dx:
        sent = _send_input_event(MOUSEEVENTF_HWHEEL, data=int(dx) * 120) and sent
    return sent
