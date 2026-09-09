"""Tiered, bounded search for the active coordinate table.

Reading all 32 MiB through PCSX2's single PINE service starves the VM and was
correlated with emulator hangs, so scanning everything is not an option.  But
pinning one hardcoded address is what limited the mod to a single map.

The compromise is a tier ladder.  Cheap, targeted reads run first and cover the
steady state; progressively wider bands run only when the cheap tiers miss, and
only on surface transitions.  The widest tier still walks memory in bounded
chunks and never issues one oversized transfer.

The record validator this relies on found no false positives across the 29
research dumps (~950 MiB), so a wider scan does not risk locking onto a
plausible-looking non-table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .memory import (
    LivenessTracker,
    LEGACY_LOCATION_TABLE,
    MIN_LOCATION_COUNT,
    PLAYER_OFFSET_FROM_TABLE,
    Location,
    find_tables,
)

# One PINE routine read is capped at 1 MiB by the client, so bands are sized to
# stay within a single transfer.
BAND_SIZE = 0x100000
TARGETED_SIZE = PLAYER_OFFSET_FROM_TABLE + 0x10

# The band containing every table observed so far.  Checked before the wide
# sweep because it is one read rather than twenty.
PRIMARY_BAND = 0x00E00000

# Dragon Adventure allocations observed live sit well inside this span.  The
# sweep covers it in 1 MiB steps, oldest-hit-first, and is only reached when the
# targeted tiers fail -- i.e. on a map whose table has moved.
SWEEP_START = 0x00300000
SWEEP_END = 0x01800000

# A full sweep is ~21 bounded reads.  Rate-limit it so a surface that genuinely
# has no table (menus, battles, loading) cannot spin the PINE service.
SWEEP_MIN_INTERVAL = 8.0

# How long the second character's position is believed after the globals last
# showed it.  One read in fifty showed the player instead; five seconds covers
# that without keeping a character who has left.
OTHER_ACTOR_MEMORY = 5.0


@dataclass(frozen=True)
class ScanWindow:
    base: int
    size: int
    tier: str


@dataclass
class TableScanner:
    """Stateful table finder that remembers where it last succeeded."""

    last_address: int | None = None
    # Liveness is a question about motion over time, so the history lives here,
    # alongside the other per-session scan state.
    liveness: LivenessTracker = field(default_factory=LivenessTracker)
    _last_sweep: float = 0.0
    _sweep_cursor: int = SWEEP_START
    tier_used: str = ""
    # Tables judged stale this visit: no player slot to prove themselves with,
    # and a settled minimap drawing none of the free destinations they list.
    rejected: set = field(default_factory=set)
    # The second character's last position, kept briefly because the globals
    # that report it flick to the player's own position for the odd read.
    _other: tuple | None = None
    _other_seen: float = 0.0

    def targeted_windows(self) -> list[ScanWindow]:
        """Cheap reads that cover the steady state."""
        windows: list[ScanWindow] = []
        seen: set[int] = set()
        for address, tier in (
            (self.last_address, "cached"),
            (LEGACY_LOCATION_TABLE, "hint"),
        ):
            if address is None or address in seen:
                continue
            seen.add(address)
            windows.append(ScanWindow(address, TARGETED_SIZE, tier))
        return windows

    def band_windows(self) -> list[ScanWindow]:
        return [ScanWindow(PRIMARY_BAND, BAND_SIZE, "band")]

    def sweep_windows(self, now: float | None = None) -> list[ScanWindow]:
        """Every band, in one pass, rate-limited.

        This used to advance one band per call so that a miss cost only a
        single megabyte read.  That was priced wrongly: measured against the
        live emulator, the whole 21 MiB range reads in 0.44 seconds (48 MiB/s),
        because the client batches READ64s.  Creeping one band at a time meant a
        map whose table sits outside the primary band -- a live map had its
        table at 0x00D7C7C0, a full band below it -- stayed undiscovered for
        twenty-odd ticks while the guide reported no map at all.

        Sweeping the range whole finds any map on the first miss, and the rate
        limit still keeps it off the steady-state path, where the cached and
        band tiers answer without ever reaching here.
        """
        moment = time.monotonic() if now is None else now
        if moment - self._last_sweep < SWEEP_MIN_INTERVAL:
            return []
        self._last_sweep = moment
        return [
            ScanWindow(base, BAND_SIZE, "sweep")
            for base in range(SWEEP_START, SWEEP_END, BAND_SIZE)
            # The band tier already covered this one.
            if base != PRIMARY_BAND
        ]

    def reset_sweep(self) -> None:
        self._sweep_cursor = SWEEP_START
        self._last_sweep = 0.0

    def accept(self, address: int, tier: str) -> None:
        self.last_address = address
        self.tier_used = tier

    def invalidate(self) -> None:
        self.last_address = None

    def reject(self, address: int) -> None:
        self.rejected.add(address)
        if self.last_address == address:
            self.last_address = None

    def note_other(self, position, now: float | None = None) -> None:
        self._other = position
        self._other_seen = time.monotonic() if now is None else now

    def other(self, now: float | None = None):
        moment = time.monotonic() if now is None else now
        if self._other is None or moment - self._other_seen > OTHER_ACTOR_MEMORY:
            return None
        return self._other

    def reset_visit(self) -> None:
        """Forget everything tied to one stay on one surface.

        Called when the world map has gone -- a cutscene, a battle, a load.
        The next map may leave this one's table resident, and a rejection or an
        acceptance that outlives its map is exactly the mistake this prevents.
        """
        self.invalidate()
        self.rejected.clear()
        self._other = None


def tables_in_window(block: bytes, window: ScanWindow) -> list[tuple[int, tuple[Location, ...]]]:
    """Parse a fetched window into candidate tables."""
    return [
        (address, locations)
        for address, locations in find_tables(block, window.base)
        if len(locations) >= MIN_LOCATION_COUNT
    ]


def choose_table(
    candidates: list[tuple[int, tuple[Location, ...]]],
    preferred: int | None = None,
    is_live=None,
) -> tuple[int, tuple[Location, ...]] | None:
    """Pick a table when a window contains more than one.

    Liveness outranks everything.  Preferring the address already in use keeps
    a stable surface from oscillating, but it must never outrank being the
    table that actually describes the player's current map -- that ordering is
    what let a resident Earth table win on other maps.
    """
    if not candidates:
        return None

    if is_live is not None:
        live = [
            (address, locations)
            for address, locations in candidates
            if is_live(address, locations)
        ]
        if not live:
            return None
        candidates = live

    if preferred is not None:
        for address, locations in candidates:
            if address == preferred:
                return address, locations
    return max(candidates, key=lambda item: (len(item[1]), -item[0]))
