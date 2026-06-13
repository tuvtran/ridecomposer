"""ridecomposer — turn one bike ride into a generative ambient piece and a poster.

Pure-stdlib DSP, written from scratch. The ride's effort curve is the song's
form; the rider's heart rate is its pulse; the route glows hot where they hurt.
"""

from __future__ import annotations

from .config import DEFAULT, Config
from .ride import Ride, RideSource, list_rides, load_ride, resolve_source

__version__ = "0.2.0"

__all__ = [
    "Config",
    "DEFAULT",
    "Ride",
    "RideSource",
    "__version__",
    "list_rides",
    "load_ride",
    "resolve_source",
]
