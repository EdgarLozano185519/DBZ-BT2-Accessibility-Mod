"""Edge-triggered global T key and direct DualSense L1 monitoring."""

from __future__ import annotations

import ctypes
import threading
import os


class KeyWatcher:
    """Samples keys on its own thread so a tap is never missed.

    Two things had to be true at once for this to be necessary, and both are.

    The guide loop runs about **four times a second** -- each pass captures and
    analyses a frame -- and a key tap lasts about a tenth of a second. Measured
    against the live loop, a 100 ms tap fell between polls on 83 of 83 gaps, so
    testing whether the key is down *right now* misses nearly every press.

    The obvious repair is GetAsyncKeyState's low bit, which latches "went down
    since the previous call". It cannot be relied on here: Windows documents
    that another process calling GetAsyncKeyState receives that bit instead,
    and PCSX2 polls the keyboard constantly. Measured over two identical runs
    of the real loop, the same three synthesised taps were seen twice, then not
    at all. A hotkey that works on a coin toss is worse than one that does not
    work, because the player cannot tell which they have.

    So the physical state is sampled far faster than a person can tap, on a
    thread of its own, and presses are counted for the loop to collect when it
    gets round to it.

    Focus is deliberately *not* checked here. Enumerating windows sixty times a
    second is wasteful, and the loop already drains presses while the player is
    reading with their screen reader.
    """

    INTERVAL = 0.015

    def __init__(self, keys) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._keys = tuple(keys)
        self._pending = {key: 0 for key in self._keys}
        self._down = {key: False for key in self._keys}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            for key in self._keys:
                down = bool(self._user32.GetAsyncKeyState(key) & 0x8000)
                if down and not self._down[key]:
                    with self._lock:
                        # Counted, not flagged: two quick presses are two
                        # questions, and the player should get two answers.
                        self._pending[key] = min(self._pending[key] + 1, 3)
                self._down[key] = down
            self._stop.wait(self.INTERVAL)

    def take(self, key: int) -> bool:
        """Collect one press, if any is waiting."""
        with self._lock:
            if self._pending.get(key, 0) > 0:
                self._pending[key] -= 1
                return True
        return False

    def drain(self) -> None:
        """Forget everything pending, for when the player was not playing."""
        with self._lock:
            for key in self._keys:
                self._pending[key] = 0

    def close(self) -> None:
        self._stop.set()


_WATCHER = None
_WATCHER_LOCK = threading.Lock()

# Every key the guide reads. One thread serves all of them.
WATCHED_KEYS = (0x54, 0x4E, 0x42, 0x52, 0x46, 0x53, 0x55, 0x47, 0x43)


def shared_watcher() -> KeyWatcher:
    global _WATCHER
    with _WATCHER_LOCK:
        if _WATCHER is None:
            _WATCHER = KeyWatcher(WATCHED_KEYS)
        return _WATCHER


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
        self._watcher = shared_watcher()
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
        # Same latch as the other keys: a tap between polls used to be lost,
        # so T worked only when held. The latch fires on a real press only, so
        # this cannot invent a teleport that the player did not ask for.
        keyboard_pressed = self._watcher.take(self.VK_T)

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
        self._watcher = shared_watcher()

    def _pressed(self, key: int) -> bool:
        return self._watcher.take(key)

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
        self._watcher = shared_watcher()

    def pressed(self) -> bool:
        fired = self._watcher.take(self.VK_G)
        # Drain the edge while the player is reading with their screen reader,
        # so returning to the game does not fire a stale press.
        return fired and desktop_input_allowed(self._user32)


class CalibrationHotkey:
    """C: start the teleport-driven map calibration, or stop one in progress.

    Its own object for the same reason as DirectionHotkey. Calibration is
    started from the world map before any objective has resolved -- which on a
    fresh map is most of the time -- so a key read further down the loop would
    appear to work only sometimes.
    """

    VK_C = 0x43

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._watcher = shared_watcher()

    def pressed(self) -> bool:
        fired = self._watcher.take(self.VK_C)
        return fired and desktop_input_allowed(self._user32)
