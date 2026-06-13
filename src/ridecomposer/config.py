"""Config — the taste layer.

Every knob that decides how a ride *reads* as music and image lives here. The
mapping IS the art; this is the one place to turn dials and re-render. Comments
say WHY a default was chosen, not just what it is — tune by ear.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Config:
    # --- audio format -------------------------------------------------------
    sample_rate: int = 32_000  # 32k is plenty for ambient and ~30% faster to render than 44.1k
    duration: float = 150.0  # whole ride compressed to ~2:30; lower it for fast iteration
    block: int = 512  # control-rate block — slow ride params held constant, voice amps ramped

    # --- musical key: A minor pentatonic ------------------------------------
    # Pentatonic is consonant by construction: there's no wrong note, so the
    # data can drive pitch freely and never clash. Dark + contemplative.
    root_hz: float = 55.0  # A1, the drone root
    scale: tuple[int, ...] = (0, 3, 5, 7, 10)  # minor pentatonic degrees (semitones)

    # --- data -> sound mapping ----------------------------------------------
    hr_pulse_div: float = 2.0  # heartbeat tempo = HR / this, as music-time BPM (150 HR -> 75)
    shimmer_threshold: float = 0.55  # normalized power above which "the suffering" enters
    shimmer_knee: float = 0.45  # power range over which shimmer fades fully in
    bell_skip: float = 0.18  # fraction of bell slots left silent — space; ambient, not busy
    bell_interval_slow: float = 1.8  # seconds between bells at low cadence
    bell_interval_fast: float = 0.45  # ...at high cadence: spinning legs -> faster notes
    detune: float = 1.004  # per-voice detune ratio for width/movement

    # --- space: from-scratch stereo cross-feedback delay --------------------
    reverb_wet: float = 0.30
    delay_tap_l: float = 0.37
    delay_tap_r: float = 0.53
    delay_feedback: float = 0.42
    delay_damp: float = 0.35  # one-pole lowpass in the feedback path (darker tails)

    # --- master -------------------------------------------------------------
    master: float = 0.85  # headroom target before the tanh soft-clip glue

    # --- poster -------------------------------------------------------------
    poster_w: int = 1400
    poster_h: int = 1980
    location: str = "SAN FRANCISCO"  # subtitle locale; --location to override per ride
    mantra: str = "suffer with purpose"

    def with_overrides(self, **kw: object) -> Config:
        """Return a copy with the given fields replaced (None values ignored)."""
        clean = {k: v for k, v in kw.items() if v is not None}
        return replace(self, **clean) if clean else self


DEFAULT = Config()
