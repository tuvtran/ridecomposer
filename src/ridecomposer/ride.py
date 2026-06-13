"""Loading rides: a directory of self-contained stream files, samplers, polyline.

A ride is one JSON file `<id>.json` carrying its own streams plus `summary` and
`reduced_polyline` — so a `streams/` folder is everything you need, no separate
`activities.json`. A legacy Strava export (activities.json + streams/ subdir) is
still supported: the activity record is used as a fallback for summary/polyline.
"""

from __future__ import annotations

import json
import os
import pathlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from .util import NUMBER, lerp

_STREAM_ALIASES: dict[str, tuple[str, ...]] = {
    "time": ("time",),
    "watts": ("watts",),
    "hr": ("heart_rate", "heartrate"),
    "cadence": ("cadence",),
    "altitude": ("altitude",),
    "grade": ("grade_smooth",),
    "velocity": ("velocity_smooth",),
    "distance": ("distance",),
}
# files that live in a ride directory but are not rides
_NON_RIDE = {"activities.json", "summary.json", "profile.json", "zones.json", "gear.json"}


class RideNotFound(Exception):
    def __init__(self, ref: str, available: Sequence[str]):
        self.ref = ref
        self.available = list(available)
        joined = ", ".join(self.available) or "(none)"
        super().__init__(f"no ride matching {ref!r}; available: {joined}")


@dataclass(slots=True)
class Ride:
    id: str
    name: str
    sport: str
    start: str
    streams: dict[str, list | None]
    polyline: str
    summary: dict[str, Any]

    @property
    def safe_name(self) -> str:
        return "".join(c if c.isalnum() else "_" for c in self.name).strip("_") or self.id

    @property
    def date(self) -> str:
        return self.start[:10]


# files_dir/index duck-type over pathlib.Path (user dirs) and importlib
# Traversable (the bundled rides) — both expose iterdir/joinpath/read_text/is_*.
Dir = Any


@dataclass(slots=True)
class RideSource:
    files_dir: Dir  # where the <id>.json ride files live
    index: dict[str, dict] = field(default_factory=dict)  # id -> activity (legacy fallback)


def resolve_source(streams_dir: str | None = None, data_dir: str | None = None) -> RideSource:
    """Resolve where rides come from.

    Order: --streams-dir > --data-dir > $RIDECOMPOSER_STREAMS > $RIDECOMPOSER_DATA
    > ./streams (if present) > the rides bundled in the package.
    """
    base: Dir
    if streams_dir:
        base = pathlib.Path(streams_dir).expanduser()
    elif data_dir:
        base = pathlib.Path(data_dir).expanduser()
    elif os.environ.get("RIDECOMPOSER_STREAMS"):
        base = pathlib.Path(os.environ["RIDECOMPOSER_STREAMS"]).expanduser()
    elif os.environ.get("RIDECOMPOSER_DATA"):
        base = pathlib.Path(os.environ["RIDECOMPOSER_DATA"]).expanduser()
    else:
        cwd_streams = pathlib.Path.cwd() / "streams"
        base = cwd_streams if cwd_streams.is_dir() else resources.files("ridecomposer").joinpath("_rides")  # noqa: E501
    files_dir = base.joinpath("streams") if base.joinpath("streams").is_dir() else base
    return RideSource(files_dir=files_dir, index=_load_index(base))


def _load_index(base: Dir) -> dict[str, dict]:
    cand = base.joinpath("activities.json")
    try:
        if cand.is_file():
            data = json.loads(cand.read_text(encoding="utf-8"))
            acts = data.get("activities", data) if isinstance(data, dict) else data
            return {str(a.get("id")): a for a in acts}
    except (OSError, ValueError):
        pass
    return {}


def _iter_ride_files(files_dir: Dir) -> Iterator[Any]:
    for entry in files_dir.iterdir():
        name = entry.name
        if name.endswith(".json") and name not in _NON_RIDE and not name.startswith("."):
            yield entry


def _read(entry: Any) -> dict:
    return json.loads(entry.read_text(encoding="utf-8"))


def _meta(raw: dict, fallback: dict, key: str, default: Any) -> Any:
    return raw.get(key) or fallback.get(key) or default


def list_rides(source: RideSource, limit: int | None = None) -> list[dict]:
    """Summaries of available rides, newest first, optionally capped to `limit`."""
    out: list[dict] = []
    for entry in _iter_ride_files(source.files_dir):
        try:
            raw = _read(entry)
        except (OSError, ValueError):
            continue
        rid = str(raw.get("activity_id") or entry.name[:-5])
        m = source.index.get(rid, {})
        out.append(
            {
                "id": rid,
                "name": _meta(raw, m, "name", rid),
                "sport_type": _meta(raw, m, "sport_type", "Ride"),
                "start_local": _meta(raw, m, "start_local", ""),
                "summary": raw.get("summary") or m.get("summary") or {},
            }
        )
    out.sort(key=lambda r: r["start_local"], reverse=True)
    return out[:limit] if limit else out


def load_ride(ref: str, source: RideSource) -> Ride:
    """Load a ride by id (filename stem) or by a fragment of its name."""
    ref = str(ref)
    entries = {entry.name[:-5]: entry for entry in _iter_ride_files(source.files_dir)}
    rid = ref if ref in entries else None
    if rid is None:
        matches = []
        for stem, entry in entries.items():
            try:
                name = str(_meta(_read(entry), source.index.get(stem, {}), "name", ""))
            except (OSError, ValueError):
                continue
            if ref.lower() in name.lower():
                matches.append(stem)
        if len(matches) == 1:
            rid = matches[0]
        else:
            raise RideNotFound(ref, matches or sorted(entries))
    raw = _read(entries[rid])
    m = source.index.get(rid, {})
    st = raw.get("streams", {})

    def col(*names: str) -> list | None:
        for n in names:
            if n in st:
                v = st[n]
                return v["data"] if isinstance(v, dict) else v
        return None

    return Ride(
        id=rid,
        name=_meta(raw, m, "name", rid),
        sport=_meta(raw, m, "sport_type", "Ride"),
        start=_meta(raw, m, "start_local", ""),
        streams={key: col(*aliases) for key, aliases in _STREAM_ALIASES.items()},
        polyline=raw.get("reduced_polyline") or m.get("reduced_polyline") or "",
        summary=raw.get("summary") or m.get("summary") or {},
    )


def sampler(times: Sequence[float], vals: Sequence[float] | None) -> Callable[[float], float]:
    """Linear interpolation of a stream at an arbitrary ride-time (seconds)."""
    if not vals:
        return lambda _t: 0.0
    pairs = [
        (times[i], vals[i])
        for i in range(len(vals))
        if isinstance(vals[i], NUMBER) and i < len(times) and isinstance(times[i], NUMBER)
    ]
    if not pairs:
        return lambda _t: 0.0
    T = [p[0] for p in pairs]
    V = [p[1] for p in pairs]
    last = len(T) - 1

    def f(t: float) -> float:
        if t <= T[0]:
            return V[0]
        if t >= T[last]:
            return V[last]
        lo, hi = 0, last
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if T[mid] <= t:
                lo = mid
            else:
                hi = mid
        span = T[hi] - T[lo]
        return V[lo] if span < 1e-9 else lerp(V[lo], V[hi], (t - T[lo]) / span)

    return f


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google encoded polyline (precision 1e-5) into (lat, lng) points."""
    pts: list[tuple[float, float]] = []
    i = lat = lng = 0
    n = len(encoded)
    while i < n:
        for is_lng in (False, True):
            shift = result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng += delta
            else:
                lat += delta
        pts.append((lat * 1e-5, lng * 1e-5))
    return pts
