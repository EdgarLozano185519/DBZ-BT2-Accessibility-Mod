"""Accessibility companion for Dragon Ball Z: Budokai Tenkaichi 2 (SLUS-21441).

The package is layered so that map discovery can be tested without PCSX2:

``memory``        pure parsing of emulated RAM through a ``MemoryView``
``scan``          tiered bounded search for the active coordinate table
``calibration``   learns each map's HUD scale from movements of the player arrow
``vision``        numpy HUD reading: markers, player arrow, HUD recognition
``profiles``      on-disk registry of discovered maps and areas
``surface``       the active navigation surface model
``objective``     graded resolution of the current story destination
``discovery``     the only module that performs live PINE I/O for navigation
``teleport``      verified, rollback-protected coordinate writes
``guide``         the resident loop tying it together
"""

from .memory import CRC, SERIAL, MapNotReady, ObjectiveNotReady

__all__ = ["SERIAL", "CRC", "MapNotReady", "ObjectiveNotReady"]
