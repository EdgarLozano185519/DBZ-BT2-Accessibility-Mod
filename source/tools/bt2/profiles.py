"""On-disk registry of discovered maps and walkable areas.

Maps are keyed by a fingerprint derived from their own coordinate geometry, and
areas by their opaque stage signature.  Both are properties the game publishes,
so a surface identifies itself without the mod holding a list of the game's
content.  Profiles are created automatically the first time a surface is seen
and enriched as calibration converges; a name is presentation only and never
gates navigation.
"""

from __future__ import annotations

import json
import os
import sys
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .calibration import Jacobian

PROFILE_VERSION = 4


def _safe_key(key: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
    return cleaned[:64] or "unknown"


@dataclass
class MapProfile:
    """A world map: its geometry fingerprint, name, and learned HUD scale.

    ``jacobian`` is the whole learned quantity -- the translation term is
    re-derived from the live player arrow every frame -- so restoring it makes
    a return visit calibrated immediately.
    """

    fingerprint: str
    name: str | None = None
    number: int = 0
    description: str | None = None
    visual_signature: list[float] = field(default_factory=list)
    point_count: int = 0
    jacobian: Jacobian | None = None
    jacobian_samples: int = 0
    jacobian_error: float = 0.0
    # The capture size the scale was learned at.  Screen measurements are
    # window-relative and the game view is pillarboxed, so a Jacobian learned at
    # one window size does not describe another.
    jacobian_capture_size: tuple[int, int] | None = None
    flight_altitude: float | None = None
    # The map's own geometry, recorded the first time it is seen.  Touring the
    # game then builds an atlas as a side effect of playing, which is the only
    # way to get every map: the tables are not in the ELF or in DAdventure.pak,
    # so they are built at runtime and cannot be extracted offline.
    points: list[dict] = field(default_factory=list)
    # Every distinct marker position seen on this map, accumulated across
    # chapters.  The game draws only the currently available destinations -- a
    # completed save still showed five of eight -- but the positions are stable,
    # so the union over several chapters approaches the full set.  Once enough
    # are collected the marker-to-point assignment can be solved outright.
    marker_positions: list[dict] = field(default_factory=list)
    # The solved world-to-screen affine, once the assignment is unique.
    map_affine: list[float] | None = None
    # Legacy map affines use absolute window pixels.  Never reuse one at a
    # different size; doing so moves every inferred destination.  New guidance
    # is screen-space and does not need this affine, but explicit diagnostics
    # and migration paths remain guarded.
    map_affine_capture_size: tuple[int, int] | None = None
    point_names: dict[int, str] = field(default_factory=dict)
    # What each destination turned out to be when the player last went there.
    # Recorded from gameplay, not from the screen.  Deliberately "last seen"
    # rather than permanent: a location that offers a free event in one chapter
    # can become the story destination in a later one, so this narrows the
    # guess without ever being treated as settled fact.
    point_kinds: dict[int, str] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.description:
            return f"{self.description}, map {self.number}" if self.number else self.description
        return f"Map {self.number}" if self.number else "New map"

    @property
    def is_named(self) -> bool:
        return bool(self.name)

    @property
    def is_calibrated(self) -> bool:
        return self.jacobian is not None

    # Recognized observations about a destination.
    KIND_STORY = "story"
    KIND_FREE = "free"
    # Nothing happens here: the player stood on the point and Cross did
    # nothing.  The coordinate table lists every destination the map has, but
    # only the currently available ones are drawn as markers -- a live frame
    # showed four markers against eight table points -- so most entries are
    # unreachable at any given time and guiding to them wastes the trip.
    KIND_NONE = "none"

    def kind_of(self, index: int) -> str | None:
        return self.point_kinds.get(index)

    def is_known_free(self, index: int) -> bool:
        return self.point_kinds.get(index) == self.KIND_FREE

    def is_known_dead(self, index: int) -> bool:
        return self.point_kinds.get(index) == self.KIND_NONE

    def worth_guiding_to(self, index: int) -> bool:
        """Whether this destination is worth offering as a default guess."""
        return not (self.is_known_dead(index) or self.is_known_free(index))

    def record_marker(self, x: float, y: float, width: int, height: int,
                      tolerance: float = 4.0) -> bool:
        """Remember a marker position, if it is one not seen before.

        Positions are kept with the capture size they were measured at: the
        game view is pillarboxed, so a window resize moves every measurement.
        """
        for existing in self.marker_positions:
            if (
                existing.get("w") == width
                and existing.get("h") == height
                and abs(existing["x"] - x) <= tolerance
                and abs(existing["y"] - y) <= tolerance
            ):
                return False
        self.marker_positions.append(
            {"x": round(x, 1), "y": round(y, 1), "w": width, "h": height}
        )
        return True

    def markers_at(self, width: int, height: int) -> list[tuple[float, float]]:
        return [
            (entry["x"], entry["y"])
            for entry in self.marker_positions
            if entry.get("w") == width and entry.get("h") == height
        ]

    def record_points(self, locations) -> bool:
        """Store this map's coordinates once.  Returns whether anything changed."""
        recorded = [
            {
                "index": location.index,
                "x": round(location.x, 3),
                "z": round(location.z, 3),
                "radius": round(location.radius, 1),
            }
            for location in locations
        ]
        if recorded == self.points:
            return False
        self.points = recorded
        return True

    def usable_at(self, capture_size) -> bool:
        """Whether the stored scale applies to the current window size."""
        if self.jacobian is None:
            return False
        if self.jacobian_capture_size is None or capture_size is None:
            return True
        return tuple(self.jacobian_capture_size) == tuple(capture_size)

    def usable_map_affine_at(self, capture_size) -> bool:
        if self.map_affine is None or self.map_affine_capture_size is None:
            return False
        if capture_size is None:
            return False
        return tuple(self.map_affine_capture_size) == tuple(capture_size)

    def to_dict(self) -> dict:
        return {
            "version": PROFILE_VERSION,
            "kind": "world",
            "fingerprint": self.fingerprint,
            "name": self.name,
            "number": self.number,
            "description": self.description,
            "visual_signature": self.visual_signature,
            "point_count": self.point_count,
            "jacobian": self.jacobian.as_list() if self.jacobian else None,
            "jacobian_samples": self.jacobian_samples,
            "jacobian_error": self.jacobian_error,
            "jacobian_capture_size": (
                list(self.jacobian_capture_size)
                if self.jacobian_capture_size
                else None
            ),
            "flight_altitude": self.flight_altitude,
            "points": self.points,
            "marker_positions": self.marker_positions,
            "map_affine": self.map_affine,
            "map_affine_capture_size": (
                list(self.map_affine_capture_size)
                if self.map_affine_capture_size
                else None
            ),
            "point_names": {str(k): v for k, v in sorted(self.point_names.items())},
            "point_kinds": {str(k): v for k, v in sorted(self.point_kinds.items())},
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, values: dict) -> "MapProfile":
        jacobian = values.get("jacobian")
        return cls(
            fingerprint=values["fingerprint"],
            name=values.get("name"),
            number=int(values.get("number", 0)),
            description=values.get("description"),
            visual_signature=list(values.get("visual_signature") or []),
            point_count=int(values.get("point_count", 0)),
            jacobian=Jacobian.from_list(jacobian) if jacobian else None,
            jacobian_samples=int(values.get("jacobian_samples", 0)),
            jacobian_error=float(values.get("jacobian_error", 0.0)),
            jacobian_capture_size=(
                tuple(values["jacobian_capture_size"])
                if values.get("jacobian_capture_size")
                else None
            ),
            points=list(values.get("points") or []),
            marker_positions=list(values.get("marker_positions") or []),
            map_affine=(
                list(values["map_affine"]) if values.get("map_affine") else None
            ),
            map_affine_capture_size=(
                tuple(values["map_affine_capture_size"])
                if values.get("map_affine_capture_size")
                else None
            ),
            flight_altitude=(
                float(values["flight_altitude"])
                if values.get("flight_altitude") is not None
                else None
            ),
            point_names={
                int(key): value
                for key, value in (values.get("point_names") or {}).items()
            },
            point_kinds={
                int(key): value
                for key, value in (values.get("point_kinds") or {}).items()
            },
            first_seen=float(values.get("first_seen", time.time())),
            last_seen=float(values.get("last_seen", time.time())),
        )


@dataclass
class AreaProfile:
    """A walkable local area, keyed by its opaque stage signature."""

    signature: str
    name: str | None = None
    number: int = 0
    observed_names: list[str] = field(default_factory=list)
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        return f"Area {self.number}" if self.number else "New area"

    @property
    def is_named(self) -> bool:
        return bool(self.name)

    def to_dict(self) -> dict:
        return {
            "version": PROFILE_VERSION,
            "kind": "area",
            "signature": self.signature,
            "name": self.name,
            "number": self.number,
            "observed_names": self.observed_names,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }

    @classmethod
    def from_dict(cls, values: dict) -> "AreaProfile":
        return cls(
            signature=values["signature"],
            name=values.get("name"),
            number=int(values.get("number", 0)),
            observed_names=list(values.get("observed_names") or []),
            first_seen=float(values.get("first_seen", time.time())),
            last_seen=float(values.get("last_seen", time.time())),
        )


class ProfileStore:
    """Reads and writes profiles under ``profiles/maps`` and ``profiles/areas``."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.maps_dir = self.root / "maps"
        self.areas_dir = self.root / "areas"
        self._maps: dict[str, MapProfile] = {}
        self._areas: dict[str, AreaProfile] = {}
        self._loaded = False

    # -- loading ---------------------------------------------------------
    def load(self) -> "ProfileStore":
        self._maps.clear()
        self._areas.clear()
        for path in sorted(self.maps_dir.glob("*.json")):
            try:
                profile = MapProfile.from_dict(json.loads(path.read_text("utf-8")))
            except (OSError, ValueError, KeyError):
                continue
            self._maps[profile.fingerprint] = profile
        for path in sorted(self.areas_dir.glob("*.json")):
            try:
                profile = AreaProfile.from_dict(json.loads(path.read_text("utf-8")))
            except (OSError, ValueError, KeyError):
                continue
            self._areas[profile.signature] = profile
        self._loaded = True
        # Migrate legacy profiles deterministically without changing custom
        # names or calibration. Assigned numbers persist on the next save.
        for profiles in (self._maps.values(), self._areas.values()):
            next_number = max((p.number for p in profiles), default=0)+1
            for profile in sorted(profiles,key=lambda p:p.first_seen):
                if not profile.number:
                    profile.number = next_number
                    next_number += 1
                    self._save_discovery(profile)
        return self

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # -- accessors -------------------------------------------------------
    @property
    def maps(self) -> dict[str, MapProfile]:
        self._ensure_loaded()
        return dict(self._maps)

    @property
    def areas(self) -> dict[str, AreaProfile]:
        self._ensure_loaded()
        return dict(self._areas)

    def map_profile(self, fingerprint: str, point_count: int = 0) -> MapProfile:
        """Return the stored profile, creating an unnamed one on first sight."""
        self._ensure_loaded()
        profile = self._maps.get(fingerprint)
        if profile is None:
            profile = MapProfile(fingerprint=fingerprint, point_count=point_count,
                                 number=max((p.number for p in self._maps.values()),default=0)+1)
            self._maps[fingerprint] = profile
            self._save_discovery(profile)
        if point_count and profile.point_count != point_count:
            profile.point_count = point_count
        profile.last_seen = time.time()
        return profile

    def area_profile(self, signature: str) -> AreaProfile:
        self._ensure_loaded()
        profile = self._areas.get(signature)
        if profile is None:
            profile = AreaProfile(signature=signature,
                                  number=max((p.number for p in self._areas.values()),default=0)+1)
            self._areas[signature] = profile
            self._save_discovery(profile)
        profile.last_seen = time.time()
        return profile

    # -- persistence -----------------------------------------------------
    def _save_discovery(self, profile) -> None:
        # Optional atlas persistence must never stop live guidance. Explicit
        # name/save commands still surface errors through save_map/save_area.
        try:
            if isinstance(profile, MapProfile):
                self.save_map(profile)
            else:
                self.save_area(profile)
        except OSError:
            pass

    @staticmethod
    def _write_atomic(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=path.stem + ".",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                handle.write(text)
            Path(handle.name).replace(path)
        except OSError:
            Path(handle.name).unlink(missing_ok=True)
            raise

    def save_map(self, profile: MapProfile) -> Path:
        self._ensure_loaded()
        self._maps[profile.fingerprint] = profile
        path = self.maps_dir / f"{_safe_key(profile.fingerprint)}.json"
        self._write_atomic(path, profile.to_dict())
        return path

    def save_area(self, profile: AreaProfile) -> Path:
        self._ensure_loaded()
        self._areas[profile.signature] = profile
        path = self.areas_dir / f"{_safe_key(profile.signature)}.json"
        self._write_atomic(path, profile.to_dict())
        return path


def default_store() -> ProfileStore:
    """Release data lives outside the installation; source runs retain their atlas."""
    if os.environ.get("BT2_DATA_DIR"):
        return ProfileStore(Path(os.environ["BT2_DATA_DIR"]) / "profiles")
    if getattr(sys,"frozen",False):
        local = os.environ.get("LOCALAPPDATA") or str(Path.home()/"AppData"/"Local")
        return ProfileStore(Path(local) / "DBZ BT2 Guide" / "profiles")
    return ProfileStore(Path(__file__).resolve().parents[2] / "profiles")
