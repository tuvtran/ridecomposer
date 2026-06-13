"""The audio engine: render a ride into a stereo ambient piece.

Five layers, each a reading of the effort curve:

  drone      root + fifth, always present; timbre opens with POWER
  pad        minor triad an octave up; swells with POWER
  shimmer    high cluster, gated above a POWER threshold — the audible suffering
  heartbeat  a sub thump at the rider's actual HEART RATE — the emotional core
  bells      sparse scale notes; pitch register from ALTITUDE, rate from CADENCE

Musical time maps linearly onto ride-elapsed time, so the song's pacing is the
shape of the ride. See `config.py` for every knob.
"""

from __future__ import annotations

import array
import math
import wave

from .config import DEFAULT, Config
from .dsp import (
    TABLE_SIZE,
    TBL_BRIGHT,
    TBL_DARK,
    feedback_delay,
    hz_from_semitones,
    xorshift01,
)
from .ride import Ride, sampler
from .util import normalizer

_TWO_PI = 2.0 * math.pi


def render(ride: Ride, cfg: Config = DEFAULT, *, verbose: bool = True) -> tuple[array.array, int]:
    """Render the ride to interleaved signed-16-bit stereo. Returns (samples, frames)."""
    sr = cfg.sample_rate
    n = int(cfg.duration * sr)
    s = ride.streams
    times = s["time"]
    if not times or len(times) < 2:
        raise ValueError(f"ride {ride.id!r} has no usable time stream")

    left = array.array("d", bytes(8 * n))
    right = array.array("d", bytes(8 * n))

    t0, t1 = times[0], times[-1]

    def ride_time(samp: int) -> float:
        return t0 + (t1 - t0) * (samp / n)

    # samplers + robust normalizers per channel of effort
    f_pow = sampler(times, s["watts"])
    n_pow = normalizer(s["watts"]) if s["watts"] else (lambda _x: 0.3)
    f_hr = sampler(times, s["hr"])
    n_hr = normalizer(s["hr"]) if s["hr"] else (lambda _x: 0.5)
    f_cad = sampler(times, s["cadence"])
    n_cad = normalizer(s["cadence"]) if s["cadence"] else (lambda _x: 0.5)
    f_alt = sampler(times, s["altitude"])
    n_alt = normalizer(s["altitude"]) if s["altitude"] else (lambda _x: 0.5)
    f_grade = sampler(times, s["grade"]) if s["grade"] else (lambda _t: 0.0)

    _sustained(cfg, left, right, n, ride_time, f_pow, n_pow, f_alt, n_alt, f_grade, verbose)
    _heartbeat(cfg, left, right, ride_time, f_hr, n_hr, verbose)
    _bells(cfg, left, right, ride_time, f_cad, n_cad, f_alt, n_alt, verbose)

    if verbose:
        print("  space (feedback delay)...", flush=True)
    feedback_delay(
        left,
        right,
        sr,
        wet=cfg.reverb_wet,
        feedback=cfg.delay_feedback,
        damp=cfg.delay_damp,
        tap_l=cfg.delay_tap_l,
        tap_r=cfg.delay_tap_r,
    )

    if verbose:
        print("  mastering...", flush=True)
    return _master(left, right, n, cfg), n


# ---------------------------------------------------------------------------
# sustained layers: drone + pad + shimmer (the block-rate, every-sample core)
# ---------------------------------------------------------------------------
def _sustained(cfg, left, right, n, ride_time, f_pow, n_pow, f_alt, n_alt, f_grade, verbose):
    block = cfg.block
    ts = TABLE_SIZE
    dark = TBL_DARK
    brt = TBL_BRIGHT
    root = cfg.root_hz
    sr = cfg.sample_rate
    half_pi = math.pi / 2

    # voice frequencies (semitones over the drone root)
    def semis(*degrees):
        return tuple(hz_from_semitones(root, d) for d in degrees)

    drone_hz = semis(0, 7)  # root + fifth
    pad_hz = semis(12, 15, 19)  # minor triad, octave up
    shim_hz = semis(24, 31, 34)  # cluster, two octaves up
    det = cfg.detune

    inc_drone = [h / sr for h in drone_hz]
    inc_pad = [(pad_hz[v] * (det if v == 2 else 1.0)) / sr for v in range(3)]
    inc_shim = [(shim_hz[v] * (1.0 + 0.003 * v)) / sr for v in range(3)]
    ph_drone = [0.0, 0.0]
    ph_pad = [0.0, 0.0, 0.0]
    ph_shim = [0.0, 0.0, 0.0]

    thr = cfg.shimmer_threshold
    knee = cfg.shimmer_knee

    def params(samp):
        rt = ride_time(samp)
        return n_pow(f_pow(rt)), n_alt(f_alt(rt)), f_grade(rt)

    nblocks = (n + block - 1) // block
    prev_p, prev_a, prev_g = params(0)
    pct = 0
    for b in range(nblocks):
        start = b * block
        end = min(start + block, n)
        cur_p, cur_a, cur_g = params(min(end, n - 1))
        d_p, d_a, d_g = cur_p - prev_p, cur_a - prev_a, cur_g - prev_g
        blen = end - start
        for k in range(blen):
            f = k / block  # ramp slow params across the block to kill zipper clicks
            power = prev_p + d_p * f
            alt = prev_a + d_a * f
            grade = prev_g + d_g * f
            bright = 0.15 + 0.85 * power  # effort opens the timbre (dark -> bright table)
            i = start + k

            # drone — root + fifth, low, breathing
            dv = 0.0
            for v in range(2):
                ph = ph_drone[v] + inc_drone[v]
                if ph >= 1.0:
                    ph -= 1.0
                ph_drone[v] = ph
                idx = ph * ts
                ii = int(idx)
                fr = idx - ii
                nx = ii + 1 if ii + 1 < ts else 0
                d0 = dark[ii]
                b0 = brt[ii]
                dval = d0 + (dark[nx] - d0) * fr
                bval = b0 + (brt[nx] - b0) * fr
                dv += dval + (bval - dval) * bright
            dv *= 0.16

            # pad — minor triad, swells with effort, soft
            pv = 0.0
            for v in range(3):
                ph = ph_pad[v] + inc_pad[v]
                if ph >= 1.0:
                    ph -= 1.0
                ph_pad[v] = ph
                idx = ph * ts
                ii = int(idx)
                fr = idx - ii
                nx = ii + 1 if ii + 1 < ts else 0
                d0 = dark[ii]
                b0 = brt[ii]
                dval = d0 + (dark[nx] - d0) * fr
                bval = b0 + (brt[nx] - b0) * fr
                pv += dval + (bval - dval) * bright
            pv *= 0.10 * (0.25 + 0.75 * power)

            # shimmer — high cluster, only above the suffering threshold
            sv = 0.0
            gate = (power - thr) / knee
            if gate > 0.001:
                if gate > 1.0:
                    gate = 1.0
                for v in range(3):
                    ph = ph_shim[v] + inc_shim[v]
                    if ph >= 1.0:
                        ph -= 1.0
                    ph_shim[v] = ph
                    idx = ph * ts
                    ii = int(idx)
                    fr = idx - ii
                    nx = ii + 1 if ii + 1 < ts else 0
                    b0 = brt[ii]
                    sv += b0 + (brt[nx] - b0) * fr
                sv *= 0.045 * gate

            mono = dv + pv + sv
            # stereo: lean by grade (climb left, descent right), widen by altitude
            pan = 0.5 + grade * 0.03 + (alt - 0.5) * 0.2
            if pan < 0.0:
                pan = 0.0
            elif pan > 1.0:
                pan = 1.0
            ang = pan * half_pi
            left[i] += mono * math.cos(ang)
            right[i] += mono * math.sin(ang)
        prev_p, prev_a, prev_g = cur_p, cur_a, cur_g
        if verbose:
            p = int(100 * (b + 1) / nblocks)
            if p >= pct + 10:
                pct = p
                print(f"  sustained {pct}%", flush=True)


# ---------------------------------------------------------------------------
# event layers: heartbeat + bells
# ---------------------------------------------------------------------------
def _heartbeat(cfg, left, right, ride_time, f_hr, n_hr, verbose):
    if verbose:
        print("  heartbeat...", flush=True)
    sr = cfg.sample_rate
    dur = cfg.duration
    t = 0.0
    while t < dur:
        samp = int(t * sr)
        hr = f_hr(ride_time(samp))
        if hr <= 0:
            hr = 60.0
        bpm = hr / cfg.hr_pulse_div  # music-time pulse, scaled from real HR
        period = 60.0 / max(bpm, 30.0)
        amp = 0.22 + 0.30 * n_hr(hr)  # harder heart -> heavier thump
        _place_thump(left, right, samp, amp, sr)
        t += period


def _bells(cfg, left, right, ride_time, f_cad, n_cad, f_alt, n_alt, verbose):
    if verbose:
        print("  bells...", flush=True)
    sr = cfg.sample_rate
    dur = cfg.duration
    scale = cfg.scale
    nscale = len(scale)
    root = cfg.root_hz
    t = 0.0
    ev = 0
    while t < dur:
        samp = int(t * sr)
        rt = ride_time(samp)
        cad = n_cad(f_cad(rt))
        alt = n_alt(f_alt(rt))
        interval = cfg.bell_interval_slow + (cfg.bell_interval_fast - cfg.bell_interval_slow) * cad
        if xorshift01(ev) >= cfg.bell_skip:  # leave some slots silent — space
            octave = 2 + int(alt * 2.99)  # climb -> higher register
            degree = int(xorshift01(ev * 7 + 1) * nscale)
            semi = scale[degree % nscale] + 12 * octave
            hz = hz_from_semitones(root, semi)
            amp = 0.10 + 0.10 * (1.0 - cad)  # softer when the legs are frantic
            pan = xorshift01(ev * 13 + 5)
            _place_bell(left, right, samp, hz, amp, pan, sr)
        t += interval
        ev += 1


def _place_thump(left, right, samp, amp, sr):
    """A heartbeat: ~55Hz sine body with a fast decay + a short higher click."""
    n = len(left)
    dur = int(0.32 * sr)
    inv_body = 1.0 / (0.09 * sr)
    inv_click = 1.0 / (0.02 * sr)
    w_body = _TWO_PI * 55.0 / sr
    w_click = _TWO_PI * 90.0 / sr
    for k in range(dur):
        j = samp + k
        if j >= n:
            break
        env = math.exp(-k * inv_body)
        body = math.sin(w_body * k) * env
        click = math.sin(w_click * k) * math.exp(-k * inv_click) * 0.4
        v = (body + click) * amp
        left[j] += v
        right[j] += v


def _place_bell(left, right, samp, hz, amp, pan, sr):
    """A soft bell: sine + a decaying octave, exponential envelope, panned."""
    n = len(left)
    dur = int(1.6 * sr)
    pan_l = math.cos(pan * math.pi / 2)
    pan_r = math.sin(pan * math.pi / 2)
    inv_env = 1.0 / (0.5 * sr)
    inv_oct = 1.0 / (0.25 * sr)
    w = _TWO_PI * hz / sr
    w2 = _TWO_PI * hz * 2.0 / sr
    for k in range(dur):
        j = samp + k
        if j >= n:
            break
        env = math.exp(-k * inv_env)
        v = (math.sin(w * k) + 0.4 * math.sin(w2 * k) * math.exp(-k * inv_oct)) * env * amp
        left[j] += v * pan_l
        right[j] += v * pan_r


# ---------------------------------------------------------------------------
# master + file output
# ---------------------------------------------------------------------------
def _master(left, right, n, cfg) -> array.array:
    """Normalize to the headroom target, tanh soft-clip for glue, to int16."""
    peak = 0.0
    for i in range(n):
        a = left[i]
        if a < 0:
            a = -a
        if a > peak:
            peak = a
        b = right[i]
        if b < 0:
            b = -b
        if b > peak:
            peak = b
    gain = cfg.master / (peak or 1.0)
    out = array.array("h", bytes(2 * 2 * n))  # int16, interleaved stereo
    drive = gain * 1.1  # push slightly into saturation for cohesion
    for i in range(n):
        out[2 * i] = int(math.tanh(left[i] * drive) * 32767)
        out[2 * i + 1] = int(math.tanh(right[i] * drive) * 32767)
    return out


def write_wav(path: str, samples: array.array, cfg: Config) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(cfg.sample_rate)
        w.writeframes(samples.tobytes())
