"""Spoken output.

Every state change the player needs -- which map loaded, whether it is
recognized, whether guidance is degraded -- is announced aloud.  Text on a
console is not reachable while playing, and the degraded modes in particular
are useless if the player cannot tell they are active.

Speech runs on its own thread so a slow synthesizer cannot stall the guide
loop, and falls back to printing when no engine is available.
"""

from __future__ import annotations

import collections
import queue
import sys
import threading


def _echo(text: str) -> None:
    """Print a line of speech to the log, without ever raising.

    The desktop app captures this worker's stdout into its log, and on Windows
    that stream is cp1252.  A single character it cannot encode -- the game
    once produced U+3327, a CJK compatibility square -- raised
    UnicodeEncodeError out of `print`, up through `say`, and out of the whole
    guide loop, which then restarted and announced "Guide recovered from
    UnicodeEncodeError".  Twice, in one session.

    A diagnostic echo must never be able to stop the mod.  Anything the log
    cannot represent is replaced, and a failure to log at all is swallowed:
    losing a log line costs a developer some context, while raising here costs
    the player the guide.
    """
    try:
        print(text)
        return
    except UnicodeEncodeError:
        pass
    except Exception:
        return
    try:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))
    except Exception:
        pass


class Speaker:
    """Queued NVDA speech, falling back to SAPI when NVDA is unavailable."""

    def __init__(self, enabled: bool = True, echo: bool = True):
        self.echo = echo
        self._queue: queue.Queue[tuple[str, bool] | None] = queue.Queue(maxsize=64)
        self._voice = None
        self._thread: threading.Thread | None = None
        self._last_spoken: str | None = None
        self._recent: collections.deque = collections.deque(
            maxlen=self.RECENT_LINES
        )
        self.available = False
        self.backend = "Text"
        self._closed = False
        if enabled and sys.platform == "win32":
            self.available = self._start()

    def _start(self) -> bool:
        self._thread = threading.Thread(
            target=self._run, name="bt2-speech", daemon=True
        )
        self._thread.start()
        return True

    def _run(self) -> None:
        from .speech_output import NvdaClient, SpeechRouter
        try:
            nvda = NvdaClient()
        except (OSError,AttributeError):
            nvda = None
        router = SpeechRouter(nvda)
        while True:
            item = self._queue.get()
            if item is None:
                router.cancel()
                break
            text, interrupt = item
            if not text:
                router.cancel()
                continue
            backend = router.speak(text,interrupt)
            if backend != self.backend:
                self.backend = backend
                if self.echo:
                    print(f"Speech output: {backend}.",flush=True)

    def _enqueue(self,item):
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                pass

    # How many recent lines "once" remembers.  A single slot was not enough:
    # two once-only notices that alternate each clear the other's record, so
    # both repeat for ever.  A live run said "Using this map's destinations
    # without confirmation" and "Tracking the minimap" back to back, eleven
    # times in three seconds, because each reset the other.
    RECENT_LINES = 8

    def say(
        self,
        text: str,
        interrupt: bool = True,
        once: bool = False,
    ) -> None:
        """Speak ``text``, cutting off whatever is still being said.

        Interrupting is the default because this narrates a game in motion.
        Queued speech meant the player heard where they *had* been while they
        were somewhere else, and long sentences made the backlog worse. Pass
        ``interrupt=False`` only for one-off notices that must not be lost.
        """
        if not text:
            return
        if once and text in self._recent:
            return
        self._last_spoken = text
        self._recent.append(text)
        if self.echo:
            _echo(text)
        if self.available and not self._closed:
            if interrupt:
                while True:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        break
            self._enqueue((text, interrupt))

    def silence(self) -> None:
        """Discard queued navigation and stop SAPI when gameplay changes."""
        self._last_spoken = None
        self._recent.clear()
        if not self.available:
            return
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        # The COM object belongs to the worker thread. An empty purge command
        # stops its current utterance without adding a battle announcement.
        self._enqueue(("", True))

    def close(self) -> None:
        if self.available and not self._closed:
            self._closed = True
            self._enqueue(None)
            if self._thread is not None:
                self._thread.join(timeout=1.0)
