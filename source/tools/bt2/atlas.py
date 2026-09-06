"""Readable map labels learned from minimap artwork, without a map catalogue."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .vision import _label, game_viewport
from .profiles import MapProfile


@dataclass(frozen=True)
class MapAppearance:
    signature: tuple[float, ...]
    description: str


def map_appearance(analysis) -> MapAppearance | None:
    """Describe only minimap terrain; player/marker ink cannot name the map.

    Resampling removes window-size dependence. A spatial hue distribution
    tolerates changing markers, dimming and the animated scene underneath the
    translucent map. Ambiguous matches are not assigned an existing name.
    """
    if analysis is None or not analysis.dragon_adventure_hud:
        return None
    viewport = game_viewport(analysis.image)
    if viewport is None:
        return None
    left, top, right, bottom = viewport
    width, height = right-left, bottom-top
    bounds = (round(left+width*.08), round(top+height*.60),
              round(left+width*.35), round(top+height*.92))
    crop = analysis.image.crop(bounds)
    pixels = np.asarray(crop.convert("RGB").resize((96,96)), dtype=float)
    high, low = pixels.max(2), pixels.min(2)
    chroma = high-low
    hue = np.zeros(high.shape)
    red, green, blue = (pixels[:,:,i] for i in range(3))
    divisor = np.maximum(chroma,1)
    for channel, value in ((red, ((green-blue)/divisor)%6),
                           (green, (blue-red)/divisor+2),
                           (blue, (red-green)/divisor+4)):
        hue[high==channel] = value[high==channel]*60
    bins = (hue/30).astype(int)%12
    # Edges in map terrain, rather than flat sky/water behind the overlay.
    contrast = np.maximum(abs(high-np.roll(high,2,axis=0)),
                          abs(high-np.roll(high,2,axis=1))) / np.maximum(high,1)
    textured = (contrast>.12) & (chroma/np.maximum(high,1)>.30) & (high>20)
    textured[:2,:] = False
    textured[:,:2] = False
    # Objective availability and player motion must not supply map identity.
    for blob in analysis.markers + analysis.white_blobs:
        x = round((blob.x-bounds[0])*96/crop.width)
        y = round((blob.y-bounds[1])*96/crop.height)
        radius = max(3,round(max(blob.width,blob.height)*96/min(crop.size)))
        if 0 <= x < 96 and 0 <= y < 96:
            textured[max(0,y-radius):min(96,y+radius+1),
                     max(0,x-radius):min(96,x+radius+1)] = False
    counts = np.bincount(bins[textured], minlength=12)
    if counts.max() < 160:
        return None
    dominant = int(counts.argmax())
    terrain = textured
    signature = []
    for row in range(4):
        for column in range(4):
            patch = bins[row*24:(row+1)*24,column*24:(column+1)*24]
            mask = terrain[row*24:(row+1)*24,column*24:(column+1)*24]
            signature.extend(np.bincount(patch[mask], minlength=12).astype(float))
    vector = np.asarray(signature)
    vector /= max(float(np.linalg.norm(vector)),1)
    colors = ("Red", "Ochre", "Yellow", "Green", "Green", "Teal",
              "Blue", "Blue", "Blue", "Purple", "Magenta", "Rose")
    palette = (np.minimum((bins-dominant)%12,(dominant-bins)%12)<=1)
    palette &= (chroma/np.maximum(high,1)>.30) & (high>20)
    labels, _ = _label(palette)
    pieces = int((np.bincount(labels.ravel())[1:]>=12).sum())
    # A description is explicitly visual, never a claim about an official name.
    shape = "islands" if pieces >= 4 else "landmass"
    return MapAppearance(tuple(float(x) for x in vector), f"{colors[dominant]} {shape}")


def appearance_similarity(first, second) -> float:
    if len(first) != len(second) or not first:
        return 0.0
    a,b = np.asarray(first),np.asarray(second)
    return float(a@b / max(float(np.linalg.norm(a)*np.linalg.norm(b)),1e-9))


class MapLabeler:
    """Latch a visit's label; colour is a description, never map identity.

    Only a confirmed live geometry key can create a durable atlas entry.
    Without that key, a provisional description is held for the whole visit.
    Memory dropouts and changing lighting do not clear the current label.
    The guide resets this object on a confirmed navigation-scene transition.
    """
    def __init__(self, store):
        self.store = store
        self.pending = None
        self.count = 0
        self.sequence = None
        self.current = None
        self.memory_key = None

    def reset(self):
        self.pending = self.current = None
        self.count = 0
        self.sequence = None
        self.memory_key = None

    def observe(self, surface, analysis, sequence):
        if surface.is_local:
            return surface
        key = None if surface.is_vision_only else surface.fingerprint
        # Steady state requires no image signature, similarity scan or write.
        if self.current is not None and (key is None or key == self.memory_key):
            return self._labeled(surface)
        if self.sequence != sequence:
            self.sequence = sequence
            if self.count == 0 or self.pending != key:
                self.pending, self.count = key, 1
            else:
                self.count += 1
            if self.count >= 3:
                appearance = map_appearance(analysis)
                if key is None:
                    # Do not persist uncertain colour-derived maps. This
                    # transient label has a single, bounded visit identity.
                    self.current = MapProfile("live-minimap", description=(
                        appearance.description if appearance else "World map"))
                else:
                    self.current = self.store.map_profile(key,len(surface.locations))
                    if appearance and not self.current.description:
                        self.current.description = appearance.description
                        self.store._save_discovery(self.current)
                self.memory_key = key
        if self.current is None or (key is not None and key != self.memory_key):
            if key is not None:
                known = self.store.maps.get(key)
                if known is not None:
                    return replace(surface,name=known.display_name,named=known.is_named)
            return surface
        return self._labeled(surface)

    def _labeled(self, surface):
        profile = self.current
        return replace(surface, name=profile.display_name, named=profile.is_named,
                       label_key=profile.fingerprint,
                       fingerprint=profile.fingerprint if surface.is_vision_only
                       else surface.fingerprint)
