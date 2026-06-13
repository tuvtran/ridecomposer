"""Export a ride (or all rides) as a self-contained, double-clickable web game.

The browser version is a *ride-along instrument*: a realtime Web Audio engine
that mirrors the offline mappings in `audio.py`, driven live by the ride data.
This module just inlines the data into the HTML template so the result has zero
dependencies and no server — it opens straight off the filesystem.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from importlib import resources

from .config import DEFAULT, Config
from .ride import Ride, decode_polyline

_STREAM_KEYS = ("time", "watts", "hr", "cadence", "altitude", "grade", "velocity", "distance")
_TOKEN = "__RIDECOMPOSER_DATA__"


def _ride_payload(ride: Ride) -> dict:
    return {
        "id": ride.id,
        "name": ride.name,
        "sport": ride.sport,
        "date": ride.date,
        "summary": ride.summary,
        "route": [[round(la, 6), round(lo, 6)] for la, lo in decode_polyline(ride.polyline)],
        "streams": {k: ride.streams.get(k) for k in _STREAM_KEYS},
    }


def _config_payload(cfg: Config) -> dict:
    # camelCase mirror of Config for the JS engine
    return {
        "duration": cfg.duration,
        "rootHz": cfg.root_hz,
        "scale": list(cfg.scale),
        "hrPulseDiv": cfg.hr_pulse_div,
        "shimmerThreshold": cfg.shimmer_threshold,
        "shimmerKnee": cfg.shimmer_knee,
        "bellSkip": cfg.bell_skip,
        "bellIntervalSlow": cfg.bell_interval_slow,
        "bellIntervalFast": cfg.bell_interval_fast,
        "detune": cfg.detune,
        "reverbWet": cfg.reverb_wet,
        "delayTapL": cfg.delay_tap_l,
        "delayTapR": cfg.delay_tap_r,
        "delayFeedback": cfg.delay_feedback,
        "delayDamp": cfg.delay_damp,
        "master": cfg.master,
        "location": cfg.location,
        "mantra": cfg.mantra,
    }


def build_web(rides: Sequence[Ride], cfg: Config = DEFAULT, default_id: str | None = None) -> str:
    """Render the standalone HTML for the given rides. First ride is the default."""
    if not rides:
        raise ValueError("need at least one ride to build the web instrument")
    payload = {
        "rides": [_ride_payload(r) for r in rides],
        "defaultId": default_id or rides[0].id,
        "config": _config_payload(cfg),
    }
    template = resources.files("ridecomposer").joinpath("_web", "template.html").read_text(
        encoding="utf-8"
    )
    return template.replace(_TOKEN, json.dumps(payload, separators=(",", ":")))
