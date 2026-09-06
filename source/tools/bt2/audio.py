"""Directional guidance tones.

Stereo position gives left/right (A/D); pitch gives forward/back (W/S); pulse
rate gives distance.  A distinct three-note rise means the player is inside the
target's trigger radius.

A second, hollower timbre marks *degraded* guidance -- a map whose HUD
projection has not been solved yet, where the bearing is honest but the story
objective could not be confirmed visually.  The player can hear the difference
without reading anything.
"""

from __future__ import annotations

import io
import math
import struct
import wave

SAMPLE_RATE = 22_050


def _render(frames: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(frames)
    return output.getvalue()


def tone(
    frequency: float,
    pan: float,
    duration: float = 0.11,
    sample_rate: int = SAMPLE_RATE,
    degraded: bool = False,
) -> bytes:
    pan = max(-1.0, min(1.0, pan))
    left_gain = math.cos((pan + 1.0) * math.pi / 4.0)
    right_gain = math.sin((pan + 1.0) * math.pi / 4.0)
    frames = bytearray()
    sample_count = int(duration * sample_rate)
    fade_count = max(1, int(0.012 * sample_rate))
    for index in range(sample_count):
        envelope = min(1.0, index / fade_count, (sample_count - index - 1) / fade_count)
        phase = 2.0 * math.pi * frequency * index / sample_rate
        sample = math.sin(phase)
        if degraded:
            # Add a hollow odd harmonic so uncalibrated guidance is audibly
            # distinct from a confirmed story objective.
            sample = 0.72 * sample + 0.28 * math.sin(3.0 * phase)
        amplitude = int(11_000 * envelope * sample)
        frames.extend(
            struct.pack("<hh", int(amplitude * left_gain), int(amplitude * right_gain))
        )
    return _render(bytes(frames))


def arrival_tone(sample_rate: int = SAMPLE_RATE) -> bytes:
    frames = bytearray()
    segment_samples = int(0.11 * sample_rate)
    for frequency in (523.25, 659.25, 783.99):
        for index in range(segment_samples):
            envelope = math.sin(math.pi * index / segment_samples)
            sample = int(
                9_000
                * envelope
                * math.sin(2.0 * math.pi * frequency * index / sample_rate)
            )
            frames.extend(struct.pack("<hh", sample, sample))
    return _render(bytes(frames))


def calibrated_tone(sample_rate: int = SAMPLE_RATE) -> bytes:
    """A short two-note rise announcing that a new map solved its projection."""
    frames = bytearray()
    segment_samples = int(0.09 * sample_rate)
    for frequency in (587.33, 880.0):
        for index in range(segment_samples):
            envelope = math.sin(math.pi * index / segment_samples)
            sample = int(
                8_000
                * envelope
                * math.sin(2.0 * math.pi * frequency * index / sample_rate)
            )
            frames.extend(struct.pack("<hh", sample, sample))
    return _render(bytes(frames))
