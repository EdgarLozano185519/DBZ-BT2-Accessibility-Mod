"""Spoken pacing for the reverse-engineering tools.

A capture session needs the player to press a button at particular moments, but
the instructions were arriving in a terminal they had to alt-tab away from the
game to read -- which loses the menu to its attract demo and makes the timing
guesswork.  Speaking each cue at the moment it applies keeps the player in the
game with their hands on the controller.

Phrases are deliberately terse.  This talks over someone mid-game, so a cue has
to land in the beat before they act: "Down", not "please press the down button
now to move the cursor to the next option".
"""

from __future__ import annotations

import time


class Voice:
    """Concise spoken cues, with a printed transcript for the log."""

    def __init__(self, enabled: bool = True):
        self.speaker = None
        if enabled:
            try:
                from bt2.speech import Speaker

                self.speaker = Speaker(enabled=True, echo=False)
            except Exception as error:  # Pacing is a convenience, never a gate.
                print(f"(voice unavailable: {type(error).__name__}: {error})")

    def say(self, text: str, interrupt: bool = True) -> None:
        print(f"  [voice] {text}")
        if self.speaker is not None:
            self.speaker.say(text, interrupt=interrupt)

    def cue(self, text: str) -> None:
        """A timing cue that must not be cut off by the next one."""
        self.say(text, interrupt=False)

    def countdown(self, seconds: int, message: str) -> None:
        """Give the player time to reach the game before anything is timed."""
        self.say(message)
        time.sleep(1.2)
        for remaining in range(seconds, 0, -1):
            self.say(str(remaining))
            time.sleep(1.0)

    def close(self) -> None:
        if self.speaker is not None:
            time.sleep(1.5)  # Let the last phrase finish before the process ends.
            self.speaker.close()
