"""Prototype: speak the title-screen menu option as the cursor moves.

This is a proof that the whole chain works end to end -- PINE reads the cursor
index, and NVDA says the label -- not the finished feature. It knows exactly one
screen, the New Game / Load Game spinner, and hard-codes its address. The real
implementation needs to know which screen is showing before it can pick a label
table, and that signal has not been found yet (see docs/memory-map.md).

    python menu_announcer.py [--seconds=120]

Press Ctrl+C to stop early.
"""

from __future__ import annotations

import sys
import time

from pine_client import PineClient

# docs/memory-map.md: the cursor on the title spinner, as index * 2.
CURSOR_ADDRESS = 0x00533A73

# Labels we supply ourselves. The game has no strings for these -- the words on
# screen are artwork -- so this table is the only place they exist as text.
LABELS = {0: "New Game", 1: "Load Game"}

# The address counts in twos. Dividing here keeps the table written in menu
# positions rather than in the raw encoding, which we do not understand yet.
INDEX_STRIDE = 2

POLL_SECONDS = 0.05


def main(seconds: float = 120.0) -> int:
    from bt2.speech import Speaker

    speaker = Speaker(enabled=True, echo=False)
    client = PineClient(timeout=10.0)

    spoken: str | None = None
    pending: int | None = None
    settled: int | None = None

    print("Announcing the title menu. Move the cursor; Ctrl+C to stop.\n")
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            raw = client.read8(CURSOR_ADDRESS)

            # Require a value to repeat before trusting it. A read can land in
            # the middle of the game updating the cursor, and announcing that
            # half-written state would speak an option that was never shown.
            if raw != pending:
                pending = raw
                time.sleep(POLL_SECONDS)
                continue
            if raw == settled:
                time.sleep(POLL_SECONDS)
                continue
            settled = raw

            if raw % INDEX_STRIDE:
                time.sleep(POLL_SECONDS)
                continue
            label = LABELS.get(raw // INDEX_STRIDE)
            if label is None:
                # Not a position this screen has. Most likely another screen
                # entirely, so say nothing rather than invent an option.
                print(f"  (unknown value {raw}, staying silent)")
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
