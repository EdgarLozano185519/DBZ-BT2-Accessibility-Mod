"""Connection check for the PCSX2 PINE link.

Confirms the whole chain the guide depends on, in order, and says which link
broke when one does:

  1. PCSX2 is listening on the PINE port at all.
  2. It answers protocol requests (emulator version, title, serial, CRC).
  3. The running disc is the build this project targets.
  4. Emulated PS2 memory can actually be read.

Results are spoken through NVDA as well as printed, because the person running
this cannot see a console while the emulator has focus.

Run it with the project virtual environment, from source/tools:

    ..\\..\\.venv\\Scripts\\python.exe pine_check.py
"""

from __future__ import annotations

import socket
import sys

from pine_client import PineClient

# The build START-HERE.txt documents as supported.
EXPECTED_SERIAL = "SLUS-21441"
EXPECTED_CRC = "FE961D28"

# The boot executable's entry point. SLUS_214.41 declares a load segment at
# vaddr 0x00100000 with e_entry at 0x00100008, and its first two words are
# genuinely zero on disc -- probing 0x00100000 reports a zero on a perfectly
# healthy connection. Probe the entry point instead, where real code starts.
PROBE_ADDRESS = 0x00100008


def _speak(speaker, text: str) -> None:
    if speaker is not None:
        speaker.say(text, interrupt=False)


def main(port: int = 28011) -> int:
    lines: list[str] = []

    try:
        from bt2.speech import Speaker

        speaker = Speaker(enabled=True, echo=False)
    except Exception:  # Speech is a convenience here, never the point of the test.
        speaker = None

    def report(text: str) -> None:
        print(text)
        lines.append(text)

    # Step 1 -- is anything listening?
    try:
        client = PineClient(port=port, timeout=5.0)
    except (ConnectionRefusedError, socket.timeout, OSError) as error:
        report(f"FAILED at step 1: nothing is listening on port {port}.")
        report(f"  {type(error).__name__}: {error}")
        report("  Check that PCSX2 is running and was started after PINE was enabled.")
        _speak(speaker, f"Connection failed. Nothing is listening on port {port}.")
        if speaker is not None:
            speaker.close()
        return 1

    report(f"Step 1 OK: connected to PCSX2 on port {port}.")

    try:
        # Step 2 -- does it answer the protocol?
        try:
            info = client.info()
        except Exception as error:
            report(f"FAILED at step 2: connected, but PINE did not answer. {error}")
            _speak(speaker, "Connected, but PINE did not answer.")
            return 1

        report(f"Step 2 OK: PINE answered. Emulator {info.emulator}.")
        report(f"  Title:  {info.title}")
        report(f"  Serial: {info.serial}")
        report(f"  CRC:    {info.crc}")
        report(f"  VM status code: {info.status}")

        # Step 3 -- is it the disc this project targets?
        serial = info.serial.strip().upper().replace("_", "-")
        crc = info.crc.strip().upper().removeprefix("0X")
        if not serial:
            report("Step 3: no disc is booted yet. Start the game, then run this again.")
            _speak(speaker, "Connected, but no game is running yet.")
            return 1
        if serial == EXPECTED_SERIAL and crc.endswith(EXPECTED_CRC):
            report(f"Step 3 OK: this is the supported build, {EXPECTED_SERIAL}.")
        else:
            report(f"Step 3 WARNING: expected {EXPECTED_SERIAL} / {EXPECTED_CRC}.")
            report("  The link works, but this is a different disc than the one targeted.")

        # Step 4 -- can we actually read emulated memory?
        try:
            value = client.read32(PROBE_ADDRESS)
        except Exception as error:
            report(f"FAILED at step 4: memory read was refused. {error}")
            _speak(speaker, "Connected, but memory could not be read.")
            return 1

        if value == 0:
            report(f"Step 4 FAILED: 0x{PROBE_ADDRESS:08X} is zero, but the boot")
            report("  executable's entry point should hold code. Either the disc has not")
            report("  booted yet, or reads are not reaching emulated memory.")
            _speak(speaker, "Connected, but memory looks empty.")
            return 1

        report(f"Step 4 OK: read 0x{value:08X} from 0x{PROBE_ADDRESS:08X}.")

        report("")
        report("All checks passed. The guide can read PS2 memory.")
        _speak(speaker, f"PINE connection working. Running {info.title}.")
        return 0
    finally:
        client.close()
        if speaker is not None:
            # Give the reader a moment to finish before the process exits.
            import time

            time.sleep(3.0)
            speaker.close()


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 28011))
