"""Prototype: speak the highlighted menu option as the cursor moves.

Proof that the whole chain works end to end -- PINE reads the cursor index and
NVDA says the label -- not the finished feature.

It still has to be told which screen it is looking at. The mod cannot yet work
that out for itself, and reading a cursor address while some other screen is up
means reading unrelated memory. Until a screen identifier is found (see
docs/memory-map.md), pass the screen on the command line:

    python menu_announcer.py main      # Main Menu
    python menu_announcer.py title     # New Game / Load Game spinner

Press Ctrl+C to stop.
"""

from __future__ import annotations

import sys
import time

from pine_client import PineClient


class Screen:
    """One menu: where its cursor lives and what its options are called.

    The labels are written here because they exist nowhere else. BT2 draws its
    menu text as artwork, so there is no string in the game to read -- this
    table is the only place those words exist as text, and the only thing that
    can be translated.
    """

    def __init__(self, name: str, address: int, stride: int, labels: dict):
        self.name = name
        self.address = address
        self.stride = stride
        self.labels = labels

    def read(self, client: PineClient) -> str | None:
        raw = client.read8(self.address)
        if raw % self.stride:
            return None
        return self.labels.get(raw // self.stride)


SCREENS = {
    # docs/memory-map.md: verified against 14 paired screen-and-RAM captures.
    "main": Screen("Main Menu", 0x00AA12A8, 1, {
        0: "Dragon Adventure",
        1: "Ultimate Battle Z",
        2: "Dragon Tournament",
        3: "Dueling",
        4: "Ultimate Training",
        5: "Evolution Z",
        6: "Item Shop",
        7: "Data Center",
        8: "Options",
        9: "Dragon Library",
    }),
    # The title spinner counts in twos. Why is still unexplained, and the main
    # menu does not do it, so the stride stays per-screen rather than global.
    "title": Screen("Title", 0x00533A73, 2, {
        0: "New Game",
        1: "Load Game",
    }),
}

POLL_SECONDS = 0.05


def main(screen: Screen, seconds: float) -> int:
    from bt2.speech import Speaker

    speaker = Speaker(enabled=True, echo=False)
    client = PineClient(timeout=10.0)

    spoken: str | None = None
    pending: int | None = None
    settled: int | None = None

    print(f"Announcing {screen.name}. Move the cursor; Ctrl+C to stop.\n")
    speaker.say(f"{screen.name} reader ready.")
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            raw = client.read8(screen.address)

            # Require a value to repeat before trusting it. A read can land
            # while the game is updating the cursor, and announcing that
            # half-written state would speak an option never actually shown.
            if raw != pending:
                pending = raw
                time.sleep(POLL_SECONDS)
                continue
            if raw == settled:
                time.sleep(POLL_SECONDS)
                continue
            settled = raw

            label = None
            if raw % screen.stride == 0:
                label = screen.labels.get(raw // screen.stride)
            if label is None:
                # Not a position this screen has, so most likely another screen
                # is up. Say nothing rather than name the wrong option: for a
                # player who cannot see, a confident error is worse than silence.
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
    name = "main"
    limit = 120.0
    for argument in sys.argv[1:]:
        if argument.startswith("--seconds="):
            limit = float(argument.split("=", 1)[1])
        elif argument in SCREENS:
            name = argument
    sys.exit(main(SCREENS[name], limit))
