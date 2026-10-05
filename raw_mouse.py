import sys

import ctypes
from ctypes import wintypes


WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
MOUSE_MOVE_ABSOLUTE = 0x0001
RIDEV_INPUTSINK = 0x00000100
RI_KEY_BREAK = 0x0001
RI_KEY_E0 = 0x0002


class _RawInputDevice(ctypes.Structure):
    _fields_ = [
        ("usage_page", wintypes.USHORT),
        ("usage", wintypes.USHORT),
        ("flags", wintypes.DWORD),
        ("target", wintypes.HWND),
    ]


class _RawInputHeader(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("size", wintypes.DWORD),
        ("device", wintypes.HANDLE),
        ("wparam", wintypes.WPARAM),
    ]


class _RawMouse(ctypes.Structure):
    _fields_ = [
        ("flags", wintypes.USHORT),
        ("button_flags", wintypes.USHORT),
        ("button_data", wintypes.USHORT),
        ("raw_buttons", wintypes.DWORD),
        ("last_x", wintypes.LONG),
        ("last_y", wintypes.LONG),
        ("extra_information", wintypes.DWORD),
    ]


class _RawInput(ctypes.Structure):
    _fields_ = [
        ("header", _RawInputHeader),
        ("mouse", _RawMouse),
    ]


class _RawKeyboard(ctypes.Structure):
    _fields_ = [
        ("make_code", wintypes.USHORT),
        ("flags", wintypes.USHORT),
        ("reserved", wintypes.USHORT),
        ("vkey", wintypes.USHORT),
        ("message", wintypes.UINT),
        ("extra_information", wintypes.ULONG),
    ]


class _RawKeyboardInput(ctypes.Structure):
    _fields_ = [("header", _RawInputHeader), ("keyboard", _RawKeyboard)]


def register_raw_input_devices(hwnd):
    if sys.platform != "win32":
        return False
    devices = (_RawInputDevice * 2)(
        _RawInputDevice(0x01, 0x02, RIDEV_INPUTSINK, hwnd),
        _RawInputDevice(0x01, 0x06, RIDEV_INPUTSINK, hwnd),
    )
    user32 = ctypes.windll.user32
    register_devices = user32.RegisterRawInputDevices
    register_devices.argtypes = [
        ctypes.POINTER(_RawInputDevice),
        wintypes.UINT,
        wintypes.UINT,
    ]
    register_devices.restype = wintypes.BOOL
    return bool(register_devices(devices, 2, ctypes.sizeof(_RawInputDevice)))


def register_raw_mouse_input(hwnd):
    return register_raw_input_devices(hwnd)


def mouse_delta_from_raw(raw_mouse):
    if raw_mouse.flags & MOUSE_MOVE_ABSOLUTE:
        return None
    return int(raw_mouse.last_x), int(raw_mouse.last_y)


def keyboard_event_from_raw(raw_keyboard):
    virtual_key = int(raw_keyboard.vkey)
    flags = int(raw_keyboard.flags)
    make_code = int(raw_keyboard.make_code)
    if virtual_key == 0xFF:
        return None
    if virtual_key == 0x10:
        if make_code == 0x2A:
            virtual_key = 0xA0
        elif make_code == 0x36:
            virtual_key = 0xA1
    elif virtual_key == 0x11:
        virtual_key = 0xA3 if flags & RI_KEY_E0 else 0xA2
    elif virtual_key == 0x12:
        virtual_key = 0xA5 if flags & RI_KEY_E0 else 0xA4
    return virtual_key, not bool(flags & RI_KEY_BREAK)


def get_raw_input_event(raw_handle):
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    size = wintypes.UINT(0)
    header_size = ctypes.sizeof(_RawInputHeader)
    result = user32.GetRawInputData(
        wintypes.HANDLE(raw_handle), RID_INPUT, None, ctypes.byref(size), header_size
    )
    if result == 0xFFFFFFFF or size.value < ctypes.sizeof(_RawInputHeader):
        return None
    buffer = ctypes.create_string_buffer(size.value)
    copied = user32.GetRawInputData(
        wintypes.HANDLE(raw_handle), RID_INPUT, buffer, ctypes.byref(size), header_size
    )
    if copied == 0xFFFFFFFF:
        return None
    header = ctypes.cast(buffer, ctypes.POINTER(_RawInputHeader)).contents
    if header.type == RIM_TYPEMOUSE and size.value >= ctypes.sizeof(_RawInput):
        raw_input = ctypes.cast(buffer, ctypes.POINTER(_RawInput)).contents
        return "mouse", mouse_delta_from_raw(raw_input.mouse)
    if header.type == RIM_TYPEKEYBOARD and size.value >= ctypes.sizeof(_RawKeyboardInput):
        raw_input = ctypes.cast(buffer, ctypes.POINTER(_RawKeyboardInput)).contents
        return "keyboard", keyboard_event_from_raw(raw_input.keyboard)
    return None


def get_raw_mouse_delta(raw_handle):
    raw_event = get_raw_input_event(raw_handle)
    if raw_event is not None and raw_event[0] == "mouse":
        return raw_event[1]
    return None


def get_raw_keyboard_event(raw_handle):
    raw_event = get_raw_input_event(raw_handle)
    if raw_event is not None and raw_event[0] == "keyboard":
        return raw_event[1]
    return None