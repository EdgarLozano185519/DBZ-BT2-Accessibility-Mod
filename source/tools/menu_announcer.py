"""Speak the highlighted menu option, working out which screen is showing.

The screen has to be identified before a cursor can be read, because each menu
reuses the same memory for its own purposes: 0x00AA12A8 is the main menu's
cursor, but on the Options screen the same byte reads 163 and on Dragon Library
208.  Announcing that as a menu position would name options at random.

Screens identify themselves.  Each one loads its own table of sprite names into
memory, so the Options screen can be recognised by the literal text
"mc_icon_saveload" sitting at a fixed address.  That is worth far more than a
state number: it is evidence that can be read back and checked, where a magic
integer can only be trusted.  An earlier candidate, 0x0034F000, looked like a
perfect screen enum across three screens and then failed the first transition it
had not been derived from -- it never reset on leaving a submenu.

Screens whose cursor is not mapped yet are still detected, and deliberately stay
silent rather than guess.

    python menu_announcer.py [--seconds=120]

Press Ctrl+C to stop.
"""

from __future__ import annotations

import sys
import time

from pine_client import PineClient


def _read_bytes(client: PineClient, address: int, count: int) -> bytes:
    return bytes(client.read8(address + offset) for offset in range(count))


class Screen:
    """A menu: how to recognise it, where its cursor is, what its options are.

    Labels live here because they exist nowhere else. BT2 draws menu text as
    artwork, so no string in the game spells "Dragon Adventure" -- this table is
    the only place those words exist as text, and the only thing translatable.
    """

    def __init__(self, name, marker_address, marker, cursor=None, stride=1,
                 labels=None):
        self.name = name
        self.marker_address = marker_address
        self.marker = marker
        self.cursor = cursor
        self.stride = stride
        self.labels = labels or {}

    def present(self, client: PineClient) -> bool:
        try:
            return _read_bytes(
                client, self.marker_address, len(self.marker)
            ) == self.marker
        except Exception:
            return False

    def option(self, client: PineClient) -> str | None:
        if self.cursor is None:
            return None
        raw = client.read8(self.cursor)
        if raw % self.stride:
            return None
        return self.labels.get(raw // self.stride)


# Markers are matched as a prefix, so a name that continues past the window it
# was found in still matches -- mc_menu_lineanim is really mc_menu_lineanime,
# and an exact-length comparison failed on that trailing letter.
SCREENS = [
    Screen("Main Menu", 0x00AA15EC, b"mc_menu_lineanim", 0x00AA12A8, 1, {
        0: "Dragon Adventure", 1: "Ultimate Battle Z", 2: "Dragon Tournament",
        3: "Dueling", 4: "Ultimate Training", 5: "Evolution Z",
        6: "Item Shop", 7: "Data Center", 8: "Options", 9: "Dragon Library",
    }),
    # The title spinner counts in twos; the main menu does not, so stride is
    # per-screen rather than a global assumption.
    Screen("Title", 0x00533D60, bytes([0x01, 0x80, 0x00, 0x00, 0x00, 0x00,
                                       0x00, 0xC4, 0xE1, 0x06, 0x53, 0x53]),
           0x00533A73, 2, {0: "New Game", 1: "Load Game"}),
    # Detected but not yet mapped. Naming the screen is useful; guessing at its
    # rows would not be. Their marker addresses come from a single visit each,
    # unlike the main menu's, which held across nineteen captures.
    Screen("Options", 0x00AFCF85, b"mc_icon_saveload"),
    Screen("Dragon Library", 0x00AB1FAF, b"mc_musicprogram_0"),
]

# The character's spoken line for each main menu option, as UTF-16 text the
# game itself holds -- unlike the option names, which are artwork. Announced on
# F12 rather than automatically: it is flavour a sighted player can ignore while
# browsing, and reading it on every move would slow navigation down.
#
# These addresses come from one PCSX2 run. The block could move between runs, so
# every read is checked for plausible text before anything is spoken.
MAIN_MENU_SUBTITLES = {
    0: 0x00CA9A42, 1: 0x00CA9B02, 2: 0x00CA9B82, 3: 0x00CA9C02, 4: 0x00CA9CC2,
    5: 0x00CA9D42, 6: 0x00CA9E02, 7: 0x00CA9EC2, 8: 0x00CA9F42, 9: 0x00CA9FC2,
}

# PCSX2 binds F1 to F6, F8 and F9; F12 is unbound, so it is free for the mod.
VK_F12 = 0x7B

MAX_SUBTITLE_BYTES = 400


def read_utf16(client: PineClient, address: int) -> str | None:
    """Read a null-terminated UTF-16LE string, or None if it is not text.

    The address is only as good as the run it was found in, so this refuses
    anything that does not look like a sentence rather than speaking whatever
    bytes happen to be there.
    """
    raw = bytearray()
    for offset in range(0, MAX_SUBTITLE_BYTES, 2):
        low = client.read8(address + offset)
        high = client.read8(address + offset + 1)
        if low == 0 and high == 0:
            break
        if high != 0 or not (low in (10, 13) or 32 <= low < 127):
            return None  # Not plain text: the block has moved, or this is data.
        raw.append(low)
    text = raw.decode("ascii", "replace").replace("\n", " ").replace("\r", " ")
    text = " ".join(text.split())
    return text if len(text) >= 4 else None


class Hotkey:
    """Edge-triggered global key, live only while the game has focus.

    Matches the pattern in bt2/hotkeys.py: the mod must not react to a key the
    player pressed into some other window.
    """

    def __init__(self, key: int):
        import ctypes

        self.key = key
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.user32.GetAsyncKeyState.restype = ctypes.c_short
        self.down = False

    def pressed(self) -> bool:
        down = bool(self.user32.GetAsyncKeyState(self.key) & 0x8000)
        fired = down and not self.down
        self.down = down
        if not fired:
            return False
        try:
            from bt2.windows import game_has_focus

            return game_has_focus()
        except Exception:
            return True


POLL_SECONDS = 0.05


def detect(client: PineClient, current: Screen | None) -> Screen | None:
    """Identify the screen, re-checking the current one first.

    Checking the likely answer before the alternatives keeps the common case to
    a single short read, rather than probing every screen on every poll.

    This tool keeps its own `Screen` and its own table, deliberately: it is the
    small standalone reader, with none of the shipped one's machinery.  So the
    marker beside each screen's cursor is all there is here -- no second
    signature, no precedence between markers, no relocation search.  See the
    Smaller, optional notes in project_status.md for the full list of what it
    no longer shares with `bt2/menus.py`.
    """
    if current is not None and current.present(client):
        return current
    for screen in SCREENS:
        if screen is not current and screen.present(client):
            return screen
    return None


def main(seconds: float) -> int:
    from bt2.speech import Speaker

    speaker = Speaker(enabled=True, echo=False)
    client = PineClient(timeout=10.0)

    screen: Screen | None = None
    spoken: str | None = None
    pending: int | None = None
    settled: int | None = None

    subtitle_key = Hotkey(VK_F12)

    print("Reading menus. Move around; F12 for the spoken line; Ctrl+C to stop.\n")
    speaker.say("Menu reader ready.")
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            found = detect(client, screen)
            if found is not screen:
                screen = found
                spoken = settled = pending = None
                name = screen.name if screen else "Unknown screen"
                print(f"[{name}]")
                speaker.say(name)
                if screen is not None and screen.cursor is None:
                    print("  (options here are not mapped yet, staying silent)")
            if screen is None or screen.cursor is None:
                subtitle_key.pressed()  # Keep the edge state fresh while idle.
                time.sleep(0.2)
                continue

            raw = client.read8(screen.cursor)

            if subtitle_key.pressed():
                address = (
                    MAIN_MENU_SUBTITLES.get(raw)
                    if screen.name == "Main Menu" else None
                )
                line = read_utf16(client, address) if address else None
                if line:
                    print(f"  [F12] {line}")
                    speaker.say(line)
                else:
                    # Either this screen has no subtitles mapped, or the text
                    # block has moved since these addresses were recorded.
                    print("  [F12] no subtitle available")
                    speaker.say("No subtitle available.")
            # Require a value to repeat before trusting it: a read can land
            # while the game is updating the cursor, and announcing that
            # half-written state would speak an option never shown.
            if raw != pending:
                pending = raw
                time.sleep(POLL_SECONDS)
                continue
            if raw == settled:
                time.sleep(POLL_SECONDS)
                continue
            settled = raw

            label = screen.labels.get(raw // screen.stride) if not (
                raw % screen.stride
            ) else None
            if label is None:
                print(f"  (value {raw} is not an option here, staying silent)")
                time.sleep(POLL_SECONDS)
                continue
            if label != spoken:
                spoken = label
                print(f"  {label}")
                speaker.say(label)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.close()
        time.sleep(1.0)
        speaker.close()
    return 0


if __name__ == "__main__":
    limit = 120.0
    for argument in sys.argv[1:]:
        if argument.startswith("--seconds="):
            limit = float(argument.split("=", 1)[1])
    sys.exit(main(limit))
