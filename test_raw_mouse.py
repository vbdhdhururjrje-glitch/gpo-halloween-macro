import ctypes
import unittest
from unittest.mock import patch

from app.input.raw_mouse import (
    MOUSE_MOVE_ABSOLUTE,
    RI_KEY_BREAK,
    RI_KEY_E0,
    _RawKeyboard,
    _RawMouse,
    keyboard_event_from_raw,
    mouse_delta_from_raw,
    register_raw_input_devices,
)


class RawMouseTests(unittest.TestCase):
    @patch("ctypes.windll.user32")
    def test_registers_mouse_and_keyboard_raw_input(self, user32):
        user32.RegisterRawInputDevices.return_value = 1

        self.assertTrue(register_raw_input_devices(123))

        devices, count, device_size = user32.RegisterRawInputDevices.call_args.args
        self.assertEqual(count, 2)
        self.assertEqual(device_size, ctypes.sizeof(type(devices)._type_))
        self.assertEqual([devices[index].usage for index in range(count)], [0x02, 0x06])
        self.assertEqual([devices[index].target for index in range(count)], [123, 123])

    def test_returns_relative_mouse_delta(self):
        raw_mouse = _RawMouse(flags=0, last_x=-12, last_y=5)
        self.assertEqual(mouse_delta_from_raw(raw_mouse), (-12, 5))

    def test_ignores_absolute_mouse_coordinates(self):
        raw_mouse = _RawMouse(flags=MOUSE_MOVE_ABSOLUTE, last_x=900, last_y=400)
        self.assertIsNone(mouse_delta_from_raw(raw_mouse))

    def test_keyboard_make_and_break_are_decoded(self):
        key_down = _RawKeyboard(make_code=0x11, flags=0, vkey=0x57)
        key_up = _RawKeyboard(make_code=0x11, flags=RI_KEY_BREAK, vkey=0x57)

        self.assertEqual(keyboard_event_from_raw(key_down), (0x57, True))
        self.assertEqual(keyboard_event_from_raw(key_up), (0x57, False))

    def test_keyboard_decoder_preserves_modifier_sides(self):
        left_shift = _RawKeyboard(make_code=0x2A, flags=0, vkey=0x10)
        right_control = _RawKeyboard(make_code=0x1D, flags=RI_KEY_E0, vkey=0x11)

        self.assertEqual(keyboard_event_from_raw(left_shift), (0xA0, True))
        self.assertEqual(keyboard_event_from_raw(right_control), (0xA3, True))


if __name__ == "__main__":
    unittest.main()