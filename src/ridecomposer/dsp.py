"""From-scratch DSP primitives — no numpy, no audio library.

Wavetables, a deterministic hash for reproducible "randomness", the soft-clip,
and the stereo feedback delay. The synth voices live in `audio.py`; these are
the parts general enough to stand alone.
"""

from __future__ import annotations

import array
import math
from collections.abc import Sequence

TABLE_SIZE = 4096
_Buf = array.array


def make_table(harmonics: Sequence[float]) -> array.array:
    """One normalized cycle of a waveform built from harmonic amplitudes.

    harmonics[0] is the fundamental, [1] the 2nd harmonic, etc. More upper
    harmonics = brighter timbre. Peak-normalized so layers stay balanced.
    """
    t = array.array("d", bytes(8 * TABLE_SIZE))
    for i in range(TABLE_SIZE):
        ph = 2.0 * math.pi * i / TABLE_SIZE
        s = 0.0
        for h, amp in enumerate(harmonics, start=1):
            s += amp * math.sin(h * ph)
        t[i] = s
    peak = max(abs(x) for x in t) or 1.0
    for i in range(TABLE_SIZE):
        t[i] /= peak
    return t


# Two timbres the drone/pad crossfade between as effort rises: dark (near-sine,
# warm) at rest, bright (rich in harmonics) under load. Effort opens the sound.
TBL_DARK = make_table([1.0, 0.18, 0.05])
TBL_BRIGHT = make_table([1.0, 0.5, 0.33, 0.22, 0.14, 0.1])


def table_at(tbl: array.array, phase: float) -> float:
    """Linear-interpolated lookup; phase in [0,1)."""
    idx = phase * TABLE_SIZE
    i = int(idx)
    frac = idx - i
    nxt = i + 1
    if nxt >= TABLE_SIZE:
        nxt = 0
    return tbl[i] + (tbl[nxt] - tbl[i]) * frac


def hz_from_semitones(root_hz: float, semitones: float) -> float:
    return root_hz * (2.0 ** (semitones / 12.0))


def xorshift01(seed: int) -> float:
    """Deterministic pseudo-random in [0,1) from an integer seed.

    Reproducible renders demand no time/Math.random seeding — variation is keyed
    off a stable event index instead, so every render is bit-identical.
    """
    x = (seed * 2654435761) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 1274126177) & 0xFFFFFFFF
    x ^= x << 5
    x &= 0xFFFFFFFF
    return (x & 0xFFFFFF) / float(0xFFFFFF)


def soft_clip(x: float) -> float:
    """tanh saturation — glue + a safety ceiling without hard digital clipping."""
    return math.tanh(x)


def feedback_delay(
    left: _Buf,
    right: _Buf,
    sr: int,
    *,
    wet: float,
    feedback: float,
    damp: float,
    tap_l: float,
    tap_r: float,
) -> None:
    """In-place stereo cross-feedback delay with a one-pole lowpass in the loop.

    Two taps of different lengths, the feedback path cross-coupled L<->R for a
    wide ping-pong, and a lowpass so each repeat gets darker (a cheap stand-in
    for air absorption). This is what turns test tones into "ambient".
    """
    n = len(left)
    dl = max(1, int(tap_l * sr))
    dr = max(1, int(tap_r * sr))
    buf_l = array.array("d", bytes(8 * dl))
    buf_r = array.array("d", bytes(8 * dr))
    lp_l = lp_r = 0.0
    for i in range(n):
        jl = i % dl
        jr = i % dr
        echo_l = buf_l[jl]
        echo_r = buf_r[jr]
        # damp the echoes (cross-coupled: left lowpass tracks the right echo)
        lp_l += damp * (echo_r - lp_l)
        lp_r += damp * (echo_l - lp_r)
        # write the input plus a fraction of the damped echo back into the line
        buf_l[jl] = left[i] + feedback * lp_l
        buf_r[jr] = right[i] + feedback * lp_r
        # and mix the wet echo into the output
        left[i] += wet * lp_l
        right[i] += wet * lp_r
