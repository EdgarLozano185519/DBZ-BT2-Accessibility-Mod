"""Edge-triggered global T key and direct DualSense L1 monitoring."""

from __future__ import annotations

import ctypes
import os


def desktop_input_allowed(user32) -> bool:
    """Typing into the desktop interface must never issue gameplay hotkeys."""
    if os.environ.get("BT2_DESKTOP_UI") != "1":
        return True
    from .windows import game_has_focus
    try:
        return game_has_focus()
    except (OSError, RuntimeError):
        return False


class TeleportHotkeys:
    DUALSENSE_VENDOR = 0x054C
    DUALSENSE_PRODUCT = 0x0CE6
    VK_T = 0x54

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._keyboard_down = False
        self._l1_down = False
        self._controller = None
        self.controller_name = None
        try:
            import hid

            devices = hid.enumerate(self.DUALSENSE_VENDOR, self.DUALSENSE_PRODUCT)
            gamepads = [
                device
                for device in devices
                if device.get("usage_page") == 1 and device.get("usage") == 5
            ]
            if gamepads:
                self._controller = hid.device()
                self._controller.open_path(gamepads[0]["path"])
                self._controller.set_nonblocking(1)
                self.controller_name = (
                    gamepads[0].get("product_string") or "DualSense controller"
                )
        except (ImportError, OSError):
            self._controller = None

    @staticmethod
    def _dualsense_l1(report: list[int]) -> bool | None:
        # USB reports put the common controller report at byte 1.  Bluetooth
        # reports add a sequence/tag byte, moving the same L1 bit one byte.
        if len(report) >= 10 and report[0] == 0x01:
            return bool(report[9] & 0x01)
        if len(report) >= 11 and report[0] == 0x31:
            return bool(report[10] & 0x01)
        return None

    def poll(self) -> str | None:
        key_state = self._user32.GetAsyncKeyState(self.VK_T) & 0xFFFF
        keyboard_down = bool(key_state & 0x8000)
        keyboard_pressed = keyboard_down and not self._keyboard_down
        self._keyboard_down = keyboard_down

        controller_pressed = False
        if self._controller is not None:
            while True:
                try:
                    report = self._controller.read(128)
                except OSError:
                    self.close()
                    break
                if not report:
                    break
                l1_down = self._dualsense_l1(report)
                if l1_down is None:
                    continue
                if l1_down and not self._l1_down:
                    controller_pressed = True
                self._l1_down = l1_down

        if not desktop_input_allowed(self._user32):
            return None
        if keyboard_pressed:
            return "T"
        if controller_pressed:
            return "L1"
        return None

    def close(self) -> None:
        if self._controller is not None:
            try:
                self._controller.close()
            except OSError:
                pass
            self._controller = None


class DestinationHotkeys:
    """Edge-triggered keys for choosing which map point to be guided to.

    These remain available for explicit diagnostic/local selection. Ordinary
    world-map story guidance follows the highlighted minimap marker directly.
    """

    VK_N = 0x4E  # next destination
    VK_B = 0x42  # previous destination
    VK_R = 0x52  # repeat the current destination aloud
    # Classifying a destination the player just came back from.  The mod can
    # see that a visit happened but not whether the story moved on; the player
    # knows that the instant it happens, so one keystroke records it.
    VK_F = 0x46  # that was a free event
    VK_S = 0x53  # that advanced the story
    VK_U = 0x55  # nothing happens there at all

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._down: dict[int, bool] = {}

    def _pressed(self, key: int) -> bool:
        state = self._user32.GetAsyncKeyState(key) & 0xFFFF
        down = bool(state & 0x8000)
        was = self._down.get(key, False)
        self._down[key] = down
        return down and not was

    def poll(self) -> str | None:
        if not desktop_input_allowed(self._user32):
            for key in (self.VK_N,self.VK_B,self.VK_R,self.VK_F,self.VK_S,self.VK_U):
                self._pressed(key)
            return None
        if self._pressed(self.VK_N):
            return "next"
        if self._pressed(self.VK_B):
            return "previous"
        if self._pressed(self.VK_R):
            return "repeat"
        if self._pressed(self.VK_F):
            return "free"
        if self._pressed(self.VK_S):
            return "story"
        if self._pressed(self.VK_U):
            return "none"
        return None


class DirectionHotkey:
    """G: which way to turn for the destination being tracked.

    Deliberately its own object, polled early in the loop. The destination
    keys are read far below the point where the loop gives up when no story
    objective has resolved, so a G pressed then was silently discarded -- the
    key appeared to work only sometimes, which is worse than not working.
    Nothing about "which way am I pointing" depends on the objective being
    ready, so nothing about it should wait for that.

    W, A, S and D are flight controls, and T, N, B, R, F and U are taken.
    """

    VK_G = 0x47

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._down = False

    def pressed(self) -> bool:
        state = self._user32.GetAsyncKeyState(self.VK_G) & 0xFFFF
        down = bool(state & 0x8000)
        fired = down and not self._down
        self._down = down
        # Drain the edge while the player is reading with their screen reader,
        # so returning to the game does not fire a stale press.
        return fired and desktop_input_allowed(self._user32)
