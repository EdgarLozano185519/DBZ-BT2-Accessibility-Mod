"""Safe coordinate teleporting.

The safety discipline from the original prototype is kept exactly: PCSX2 must
be paused by hand (PINE writes race the CPU thread upstream), the surface is
revalidated immediately before writing, every write is verified by reading it
back inside the same transaction, and a failed verification restores the
snapshot.

What changed is which addresses get written.  The mirror set is discovered per
frame by quorum rather than being a fixed list, so a map that leaves one render
slot unpopulated is still teleportable, and the read-back verification is what
makes trusting a discovered set safe.
"""

from __future__ import annotations

import math
import struct

from .memory import (
    LOCAL_PLAYER_MIRROR_BLOCK,
    LOCAL_PLAYER_MIRROR_BLOCK_SIZE,
    LOCAL_TELEPORT_STANDOFF,
    Location,
    MapNotReady,
    PLAYER_RENDER_CANDIDATES,
    PLAYER_SIMULATION_CANDIDATES,
    discover_world_mirrors,
    find_local_player_mirrors,
)
from .surface import Surface

# How deep into a destination's sphere a world teleport aims, as a fraction of
# its radius.  The overworld is flown far above the destinations -- points sit
# at y = 0 while the player cruises near -169 -- and the game tests a sphere, so
# altitude is the largest single term in that distance.  Landing on the
# horizontal centre while keeping cruise altitude spent 169 of a 200-unit radius
# on height alone, leaving about 31 units of margin and 107 of horizontal slack;
# ordinary drift then carried the player back out.  Worse, a destination whose
# radius is smaller than the altitude offset could not be entered by teleport at
# all, because the landing was outside the volume before the player moved.
#
# Half the radius keeps a wide margin in every axis without dropping the player
# onto the terrain, and altitude is only changed when it needs to be.
WORLD_TELEPORT_DEPTH_FRACTION = 0.5


def _world_landing(
    player: tuple[float, float, float], target: Location
) -> tuple[float, float, float]:
    """Where to put the player so the landing sits inside the sphere.

    Altitude is preserved when it is already comfortably inside, so a normal
    teleport still leaves the player at the height they were flying at.  It is
    corrected only far enough to clear the margin, and always toward the point
    from whichever side the player is on.
    """
    vertical = player[1] - target.y
    limit = target.radius * WORLD_TELEPORT_DEPTH_FRACTION
    if abs(vertical) <= limit:
        return (target.x, player[1], target.z)
    sign = 1.0 if vertical > 0.0 else -1.0
    return (target.x, target.y + sign * limit, target.z)


def _require_paused(pine) -> None:
    status = pine.status()
    if status not in (0, 1):
        raise RuntimeError(f"PCSX2 VM is not ready (status {status})")
    if status != 1:
        raise RuntimeError(
            "PCSX2 must be paused manually before teleporting. Running-game "
            "PINE writes can race the CPU thread and freeze the emulator."
        )


def _local_landing(
    pine, surface: Surface, target: Location
) -> tuple[tuple[int, ...], tuple[float, float, float], tuple[int, ...]]:
    player = pine.read_vector3(surface.player_address)
    block = pine.read_aligned_range(
        LOCAL_PLAYER_MIRROR_BLOCK, LOCAL_PLAYER_MIRROR_BLOCK_SIZE
    )
    mirrors = find_local_player_mirrors(block, LOCAL_PLAYER_MIRROR_BLOCK)
    if not mirrors:
        raise MapNotReady("The local player mirrors are not internally consistent")

    away_x = player[0] - target.x
    away_z = player[2] - target.z
    planar = math.hypot(away_x, away_z)
    if planar <= 0.01:
        forward = surface.local_forward or (0.0, 1.0)
        away_x, away_z = -forward[0], -forward[1]
        planar = max(math.hypot(away_x, away_z), 1.0)
    landing = (
        target.x + LOCAL_TELEPORT_STANDOFF * away_x / planar,
        target.y,
        target.z + LOCAL_TELEPORT_STANDOFF * away_z / planar,
    )
    return mirrors, landing, (0, 4, 8)


def teleport(pine, surface: Surface, target: Location, rediscover) -> int:
    """Move the player across every live mirror, or restore and fail."""
    if surface.requires_world_return:
        raise RuntimeError(
            "This local area has no verified coordinate target; arm teleport "
            "in the guide, press R1 normally, and it will run on the world map"
        )
    _require_paused(pine)

    # Revalidate immediately before writing so a hotkey pressed during a
    # world/local transition cannot touch actor slots.
    current = rediscover()
    if current.identity != surface.identity:
        raise MapNotReady("The navigation surface changed before teleporting")

    if current.is_local:
        if current.requires_world_return:
            raise MapNotReady("The local interaction disappeared before teleporting")
        if target.index >= len(current.locations):
            raise MapNotReady("The local interaction changed before teleporting")
        mirrors, landing, coordinate_offsets = _local_landing(
            pine, current, current.locations[target.index]
        )
    else:
        readings = dict(
            zip(
                PLAYER_SIMULATION_CANDIDATES + PLAYER_RENDER_CANDIDATES,
                pine.read_vector3_many(
                    PLAYER_SIMULATION_CANDIDATES + PLAYER_RENDER_CANDIDATES
                ),
            )
        )
        mirror_set = discover_world_mirrors(readings)
        mirrors = mirror_set.all_addresses
        landing = _world_landing(mirror_set.position, target)
        # Y is written too.  It used to be left alone, which is what made a
        # teleport land short of the volume it was aiming at.
        coordinate_offsets = (0, 4, 8)

    write_addresses = tuple(
        address + offset for address in mirrors for offset in coordinate_offsets
    )
    originals = pine.read32_many(write_addresses)
    landing_words = tuple(
        struct.unpack("<I", struct.pack("<f", coordinate))[0] for coordinate in landing
    )
    selected = tuple(landing_words[offset // 4] for offset in coordinate_offsets)
    expected = tuple(value for _address in mirrors for value in selected)

    observed = pine.write32_many_and_read32_many(
        tuple(zip(write_addresses, expected)), write_addresses
    )
    if observed != expected:
        restored = pine.write32_many_and_read32_many(
            tuple(zip(write_addresses, originals)), write_addresses
        )
        if restored != originals:
            raise RuntimeError(
                "Teleport verification failed and the original coordinates "
                "could not be confirmed"
            )
        raise RuntimeError(
            "Teleport verification failed; original coordinates were restored"
        )
    return len(mirrors)
