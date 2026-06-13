#!/usr/bin/env python3
"""
ride-as-composition — turn a bike ride into a piece of music and a poster.

A ride is a time-series of effort: power, heart rate, cadence, altitude, grade.
This reads one ride's Strava streams and renders two artifacts, both procedurally
driven by the actual ride:

  out/<name>.wav  — a generative ambient piece. The climb is the build, the
                    redline is the drop. Your heart rate is the pulse.
  out/<name>.svg  — a poster: the route, glowing hot where you suffered,
                    the elevation profile, the numbers.

Everything is written from scratch, pure stdlib. No numpy, no audio library.
I write every oscillator, every envelope, the reverb, and the projection.

The mapping (data -> music) lives in CONFIG + the build_* functions. That's the
taste layer — change it, re-run, hear a different reading of the same ride.

Usage:  python3 compose.py [activity_id]
"""

import json, math, os, sys, wave, array

# ----------------------------------------------------------------------------
# CONFIG — the knobs. This is where taste lives.
# ----------------------------------------------------------------------------
VAULT = "/Users/tutran/Documents/tut"
DATA  = os.path.join(VAULT, "\U0001F916 genai/data/strava")
HERE  = os.path.dirname(os.path.abspath(__file__))
OUT   = os.path.join(HERE, "out")

RIDE_ID = sys.argv[1] if len(sys.argv) > 1 else "18879712215"  # "thurs", 2026-06-11

SR       = 32000          # sample rate. 32k is plenty for ambient, ~30% faster than 44.1k.
DUR      = 150.0          # seconds of music. The whole ride, compressed to ~2:30.
BLOCK    = 512            # control-rate block; ride params held constant per block.

# Musical key: A minor pentatonic. Foolproof-consonant, contemplative.
ROOT_HZ  = 55.0           # A1, the drone root.
PENT     = [0, 3, 5, 7, 10]   # minor pentatonic scale degrees (semitones)

HR_PULSE_DIV = 2.0        # heartbeat pulse runs at HR/this as BPM in music-time.
WET      = 0.30           # reverb/delay wet mix.
MASTER   = 0.85           # headroom before soft-clip.

MANTRA   = "suffer with purpose"

# ----------------------------------------------------------------------------
# small math helpers
# ----------------------------------------------------------------------------
def lerp(a, b, t): return a + (b - a) * t
def clamp(x, lo=0.0, hi=1.0): return lo if x < lo else hi if x > hi else x

def percentile(sorted_vals, p):
    if not sorted_vals: return 0.0
    i = p * (len(sorted_vals) - 1)
    lo = int(i); hi = min(lo + 1, len(sorted_vals) - 1)
    return lerp(sorted_vals[lo], sorted_vals[hi], i - lo)

def normalizer(vals):
    """Return f(x)->0..1 using robust 5th/95th percentiles (ignore spikes)."""
    clean = sorted(v for v in vals if isinstance(v, (int, float)))
    lo = percentile(clean, 0.05); hi = percentile(clean, 0.95)
    if hi - lo < 1e-9: hi = lo + 1.0
    return lambda x: clamp((x - lo) / (hi - lo))

# ----------------------------------------------------------------------------
# load the ride
# ----------------------------------------------------------------------------
def load_ride(rid):
    s = json.load(open(os.path.join(DATA, "streams", rid + ".json")))
    st = s["streams"]
    def col(*names):
        for n in names:
            if n in st:
                v = st[n]
                return v["data"] if isinstance(v, dict) else v
        return None
    streams = {
        "time":     col("time"),
        "watts":    col("watts"),
        "hr":       col("heart_rate", "heartrate"),
        "cadence":  col("cadence"),
        "altitude": col("altitude"),
        "grade":    col("grade_smooth"),
        "velocity": col("velocity_smooth"),
        "distance": col("distance"),
    }
    acts = json.load(open(os.path.join(DATA, "activities.json")))
    acts = acts if isinstance(acts, list) else acts.get("activities", acts)
    act = next((a for a in acts if str(a.get("id")) == rid), {})
    return {
        "id": rid,
        "name": s.get("name", "ride"),
        "sport": s.get("sport_type", "Ride"),
        "start": s.get("start_local", ""),
        "streams": streams,
        "polyline": act.get("reduced_polyline", ""),
        "summary": act.get("summary", {}),
    }

def sampler(times, vals):
    """Linear interpolation of a stream at an arbitrary ride-time (seconds)."""
    if not vals: return lambda t: 0.0
    pairs = [(times[i], vals[i]) for i in range(len(vals))
             if isinstance(vals[i], (int, float)) and isinstance(times[i], (int, float))]
    if not pairs: return lambda t: 0.0
    T = [p[0] for p in pairs]; V = [p[1] for p in pairs]
    def f(t):
        if t <= T[0]: return V[0]
        if t >= T[-1]: return V[-1]
        lo, hi = 0, len(T) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if T[mid] <= t: lo = mid
            else: hi = mid
        span = T[hi] - T[lo]
        return V[lo] if span < 1e-9 else lerp(V[lo], V[hi], (t - T[lo]) / span)
    return f

# ----------------------------------------------------------------------------
# AUDIO ENGINE — additive synthesis, written from scratch
# ----------------------------------------------------------------------------
TBL = 4096
def make_table(harmonics):
    """One cycle of a waveform built from harmonic amplitudes."""
    t = array.array("d", [0.0]) * TBL
    for i in range(TBL):
        ph = 2.0 * math.pi * i / TBL
        s = 0.0
        for h, amp in enumerate(harmonics, start=1):
            s += amp * math.sin(h * ph)
        t[i] = s
    peak = max(abs(x) for x in t) or 1.0
    for i in range(TBL): t[i] /= peak
    return t

TBL_DARK   = make_table([1.0, 0.18, 0.05])                 # near-sine, warm
TBL_BRIGHT = make_table([1.0, 0.5, 0.33, 0.22, 0.14, 0.1]) # opens up under effort

def note_hz(semi):  return ROOT_HZ * (2.0 ** (semi / 12.0))

def scale_note(degree_idx, octave):
    return PENT[degree_idx % len(PENT)] + 12 * octave

# deterministic pseudo-random so renders are reproducible (no Math.random vibes)
def rnd(seed):
    x = (seed * 2654435761) & 0xFFFFFFFF
    x ^= (x >> 13); x = (x * 1274126177) & 0xFFFFFFFF
    return (x & 0xFFFFFF) / 0xFFFFFF

def render(ride):
    N = int(DUR * SR)
    L = array.array("d", [0.0]) * N
    R = array.array("d", [0.0]) * N
    s = ride["streams"]
    T = s["time"]
    t0, t1 = T[0], T[-1]

    # samplers + normalizers per channel of effort
    fp = sampler(T, s["watts"]);    np_ = normalizer(s["watts"]) if s["watts"] else (lambda x: 0.3)
    fh = sampler(T, s["hr"]);       nh = normalizer(s["hr"]) if s["hr"] else (lambda x: 0.5)
    fc = sampler(T, s["cadence"]);  nc = normalizer(s["cadence"]) if s["cadence"] else (lambda x: 0.5)
    fa = sampler(T, s["altitude"]); na = normalizer(s["altitude"]) if s["altitude"] else (lambda x: 0.5)
    fg = sampler(T, s["grade"]) if s["grade"] else (lambda t: 0.0)

    def ride_time(samp): return lerp(t0, t1, samp / N)
    def at(samp):
        rt = ride_time(samp)
        return {
            "p": np_(fp(rt)), "h": nh(fh(rt)), "c": nc(fc(rt)),
            "a": na(fa(rt)), "g": fg(rt), "hr_raw": fh(rt), "cad_raw": fc(rt),
        }

    # ---- block-based sustained layers: drone + pad + effort shimmer ----
    # phases for each oscillator
    drone = [(note_hz(0), 0.0), (note_hz(7), 0.0)]            # root + fifth
    pad   = [(note_hz(12), 0.0), (note_hz(12+3), 0.0), (note_hz(12+7), 0.0)]  # minor triad
    shim  = [(note_hz(24+0), 0.0), (note_hz(24+7), 0.0), (note_hz(24+10), 0.0)]
    ph_drone = [0.0, 0.0]; ph_pad = [0.0, 0.0, 0.0]; ph_shim = [0.0, 0.0, 0.0]
    DET = 1.004  # detune for width/movement

    nblocks = (N + BLOCK - 1) // BLOCK
    prev = at(0)
    pct = 0
    for b in range(nblocks):
        start = b * BLOCK
        end = min(start + BLOCK, N)
        cur = at(min(end, N - 1))
        for ch, (p0, p1, key) in enumerate([(prev, cur, "")]):
            pass
        # per-sample within block, ramp the slow params from prev->cur
        blen = end - start
        for k in range(blen):
            f = k / BLOCK
            P = lerp(prev["p"], cur["p"], f)
            H = lerp(prev["h"], cur["h"], f)
            A = lerp(prev["a"], cur["a"], f)
            G = lerp(prev["g"], cur["g"], f)
            bright = clamp(0.15 + 0.85 * P)         # effort opens the timbre
            i = start + k

            # drone: always there, low, breathing
            dv = 0.0
            for v, (hz, _) in enumerate(drone):
                ph_drone[v] = (ph_drone[v] + hz / SR) % 1.0
                idx = ph_drone[v] * TBL
                ii = int(idx); fr = idx - ii
                dark = TBL_DARK[ii] + (TBL_DARK[(ii+1)%TBL]-TBL_DARK[ii])*fr
                brt  = TBL_BRIGHT[ii] + (TBL_BRIGHT[(ii+1)%TBL]-TBL_BRIGHT[ii])*fr
                dv += lerp(dark, brt, bright)
            dv *= 0.16

            # pad: minor triad, swells with effort, soft
            pv = 0.0
            for v, (hz, _) in enumerate(pad):
                hzd = hz * (DET if v == 2 else 1.0)
                ph_pad[v] = (ph_pad[v] + hzd / SR) % 1.0
                idx = ph_pad[v] * TBL; ii = int(idx); fr = idx - ii
                dark = TBL_DARK[ii] + (TBL_DARK[(ii+1)%TBL]-TBL_DARK[ii])*fr
                brt  = TBL_BRIGHT[ii] + (TBL_BRIGHT[(ii+1)%TBL]-TBL_BRIGHT[ii])*fr
                pv += lerp(dark, brt, bright)
            pv *= 0.10 * (0.25 + 0.75 * P)

            # shimmer: high cluster, only on real efforts (P high). The suffering.
            sv = 0.0
            gate = clamp((P - 0.55) / 0.45)
            if gate > 0.001:
                for v, (hz, _) in enumerate(shim):
                    hzd = hz * (1.0 + 0.003 * v)
                    ph_shim[v] = (ph_shim[v] + hzd / SR) % 1.0
                    idx = ph_shim[v] * TBL; ii = int(idx); fr = idx - ii
                    sv += TBL_BRIGHT[ii] + (TBL_BRIGHT[(ii+1)%TBL]-TBL_BRIGHT[ii])*fr
                sv *= 0.045 * gate

            mono = dv + pv + sv
            # stereo: pan by grade (climb leans left, descent right), width by altitude
            pan = clamp(0.5 + G * 0.03 + (A - 0.5) * 0.2, 0.0, 1.0)
            L[i] += mono * math.cos(pan * math.pi / 2)
            R[i] += mono * math.sin(pan * math.pi / 2)
        prev = cur
        np2 = int(100 * (b + 1) / nblocks)
        if np2 >= pct + 10:
            pct = np2; print(f"    pad/drone {pct}%", flush=True)

    # ---- event layer: heartbeat sub-pulse at your actual HR ----
    print("    heartbeat...", flush=True)
    t = 0.0
    while t < DUR:
        samp = int(t * SR)
        hr = fh(ride_time(samp))
        if hr <= 0: hr = 60.0
        bpm = hr / HR_PULSE_DIV                  # music-time pulse, scaled from HR
        period = 60.0 / max(bpm, 30.0)
        amp = 0.22 + 0.30 * nh(hr)               # harder heart, heavier thump
        place_thump(L, R, samp, amp)
        t += period

    # ---- event layer: bells, pitch by altitude, rate by cadence ----
    print("    bells...", flush=True)
    t = 0.0; ev = 0
    while t < DUR:
        samp = int(t * SR)
        cad = nc(fc(ride_time(samp)))
        alt = na(fa(ride_time(samp)))
        interval = lerp(1.8, 0.45, cad)          # spinning legs -> faster notes
        if rnd(ev) < 0.82:                        # leave space; ambient, not busy
            octave = 2 + int(alt * 2.99)         # climb -> higher register
            degree = int(rnd(ev * 7 + 1) * len(PENT))
            hz = note_hz(scale_note(degree, octave))
            amp = 0.10 + 0.10 * (1.0 - cad)      # softer when frantic
            pan = rnd(ev * 13 + 5)
            place_bell(L, R, samp, hz, amp, pan)
        t += interval; ev += 1

    # ---- space: stereo feedback delay (cheap, lush, from scratch) ----
    print("    space (delay)...", flush=True)
    feedback_delay(L, R)

    # ---- master: normalize + gentle soft-clip glue ----
    print("    mastering...", flush=True)
    peak = max(max(abs(x) for x in L), max(abs(x) for x in R)) or 1.0
    g = MASTER / peak
    out = array.array("h", [0]) * (N * 2)
    for i in range(N):
        l = math.tanh(L[i] * g * 1.1); r = math.tanh(R[i] * g * 1.1)
        out[2*i]   = int(clamp(l, -1, 1) * 32767)
        out[2*i+1] = int(clamp(r, -1, 1) * 32767)
    return out, N

def place_thump(L, R, samp, amp):
    """A heartbeat: ~55Hz sine with a fast percussive decay + a soft click."""
    dur = int(0.32 * SR)
    for k in range(dur):
        if samp + k >= len(L): break
        env = math.exp(-k / (0.09 * SR))
        body = math.sin(2*math.pi*55*k/SR) * env
        click = math.sin(2*math.pi*90*k/SR) * math.exp(-k/(0.02*SR)) * 0.4
        v = (body + click) * amp
        L[samp+k] += v; R[samp+k] += v

def place_bell(L, R, samp, hz, amp, pan):
    """A soft bell: sine + octave, exponential decay. Detuned for shimmer."""
    dur = int(1.6 * SR)
    panl = math.cos(pan*math.pi/2); panr = math.sin(pan*math.pi/2)
    for k in range(dur):
        if samp + k >= len(L): break
        env = math.exp(-k / (0.5 * SR))
        v = (math.sin(2*math.pi*hz*k/SR)
             + 0.4*math.sin(2*math.pi*hz*2.0*k/SR)*math.exp(-k/(0.25*SR))) * env * amp
        L[samp+k] += v * panl; R[samp+k] += v * panr

def feedback_delay(L, R):
    """Two-tap stereo feedback delay with a one-pole lowpass in the loop."""
    N = len(L)
    dL = int(0.37 * SR); dR = int(0.53 * SR)
    fb = 0.42; wet = WET
    lpL = lpR = 0.0; damp = 0.35
    for i in range(N):
        sl = L[i - dL] if i >= dL else 0.0
        sr = R[i - dR] if i >= dR else 0.0
        lpL = lpL + damp * (sl - lpL)
        lpR = lpR + damp * (sr - lpR)
        L[i] += wet * lpL; R[i] += wet * lpR
        # cross-feed the feedback for width
        if i >= dL: L[i - dL] += fb * lpR * 0.0  # (history already consumed; no-op guard)
    # second pass for feedback tails (feed delayed output back in)
    for i in range(N):
        if i >= dL: L[i] += fb * wet * (L[i - dL])
        if i >= dR: R[i] += fb * wet * (R[i - dR])

# ----------------------------------------------------------------------------
# VISUAL ENGINE — SVG poster, from scratch
# ----------------------------------------------------------------------------
def decode_polyline(p):
    pts, i, lat, lng = [], 0, 0, 0
    while i < len(p):
        for is_lng in (0, 1):
            shift = result = 0
            while True:
                b = ord(p[i]) - 63; i += 1
                result |= (b & 0x1f) << shift; shift += 5
                if b < 0x20: break
            d = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng: lng += d
            else: lat += d
        pts.append((lat * 1e-5, lng * 1e-5))
    return pts

# inferno-ish ramp: black -> purple -> red -> orange -> pale yellow (heat = effort)
RAMP = [(0.0,(8,4,18)),(0.25,(66,10,104)),(0.5,(147,38,103)),
        (0.75,(221,81,58)),(0.9,(252,165,10)),(1.0,(252,255,164))]
def heat(x):
    x = clamp(x)
    for j in range(len(RAMP)-1):
        a, ca = RAMP[j]; b, cb = RAMP[j+1]
        if x <= b:
            f = (x-a)/(b-a) if b > a else 0
            return tuple(int(lerp(ca[k], cb[k], f)) for k in range(3))
    return RAMP[-1][1]
def rgb(c): return "#%02x%02x%02x" % c

def fmt_time(sec):
    sec = int(sec); h = sec//3600; m = (sec%3600)//60
    return f"{h}:{m:02d}" if h else f"{m}:{sec%60:02d}"

def poster(ride):
    W, Hh = 1400, 1980
    s = ride["streams"]; sm = ride["summary"]; T = s["time"]
    fp = sampler(T, s["watts"]); np_ = normalizer(s["watts"]) if s["watts"] else (lambda x: .3)
    fh = sampler(T, s["hr"])
    t0, t1 = T[0], T[-1]
    pts = decode_polyline(ride["polyline"])

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{Hh}" '
           f'viewBox="0 0 {W} {Hh}" font-family="Helvetica Neue, Arial, sans-serif">']
    svg.append(f'<rect width="{W}" height="{Hh}" fill="#0a0a0e"/>')
    svg.append('<defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
               '<feGaussianBlur stdDeviation="6" result="b"/>'
               '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
               '</filter></defs>')

    # ---- title ----
    name = ride["name"].upper()
    date = ride["start"][:10]
    svg.append(f'<text x="90" y="150" fill="#f4f4f6" font-size="92" '
               f'font-weight="700" letter-spacing="6">{name}</text>')
    svg.append(f'<text x="94" y="200" fill="#7a7a86" font-size="30" '
               f'letter-spacing="10">{date} · SAN FRANCISCO · {ride["sport"].upper()}</text>')

    # ---- route map, colored by effort ----
    if pts:
        mlat = sum(p[0] for p in pts)/len(pts)
        kx = math.cos(math.radians(mlat))
        xs = [p[1]*kx for p in pts]; ys = [p[0] for p in pts]
        x0, x1 = min(xs), max(xs); y0, y1 = min(ys), max(ys)
        rw = x1-x0 or 1e-6; rh = y1-y0 or 1e-6
        # fit into a box
        bx, by, bw, bh = 90, 280, W-180, 1060
        scale = min(bw/rw, bh/rh)
        ox = bx + (bw - rw*scale)/2; oy = by + (bh - rh*scale)/2
        def proj(la, lo):
            return (ox + (lo*kx - x0)*scale, oy + (y1 - la)*scale)
        # cumulative length -> progress, to look up effort along the route
        cum = [0.0]
        for k in range(1, len(pts)):
            cum.append(cum[-1] + math.dist(pts[k], pts[k-1]))
        total = cum[-1] or 1.0
        def effort_at(prog):
            return np_(fp(lerp(t0, t1, prog)))
        # draw segment-by-segment, colored + glowing
        for k in range(1, len(pts)):
            x_a, y_a = proj(*pts[k-1]); x_b, y_b = proj(*pts[k])
            e = effort_at(cum[k]/total)
            col = rgb(heat(e)); wdt = 2.5 + 6.0*e
            svg.append(f'<line x1="{x_a:.1f}" y1="{y_a:.1f}" x2="{x_b:.1f}" y2="{y_b:.1f}" '
                       f'stroke="{col}" stroke-width="{wdt:.1f}" stroke-linecap="round" '
                       f'opacity="0.92" filter="url(#glow)"/>')
        # start dot
        sx, sy = proj(*pts[0])
        svg.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="#f4f4f6"/>')

    # ---- elevation ribbon, colored by effort, HR overlaid ----
    ex, ey, ew, eh = 90, 1380, W-180, 300
    alt = s["altitude"]; dist = s["distance"]
    if alt and dist:
        amin = min(a for a in alt if isinstance(a,(int,float)))
        amax = max(a for a in alt if isinstance(a,(int,float)))
        dmax = max(d for d in dist if isinstance(d,(int,float))) or 1.0
        arng = (amax - amin) or 1.0
        def ept(i):
            x = ex + (dist[i]/dmax)*ew
            y = ey + eh - ((alt[i]-amin)/arng)*eh
            return x, y
        # filled silhouette
        path = f'M {ex} {ey+eh} '
        for i in range(len(alt)):
            x, y = ept(i); path += f'L {x:.1f} {y:.1f} '
        path += f'L {ex+ew} {ey+eh} Z'
        svg.append(f'<path d="{path}" fill="#16161e"/>')
        # colored ridge by effort
        for i in range(1, len(alt)):
            xa, ya = ept(i-1); xb, yb = ept(i)
            e = np_(fp(T[i])) if i < len(T) else 0.3
            svg.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" '
                       f'stroke="{rgb(heat(e))}" stroke-width="4"/>')
        # HR overlay (thin, cool)
        hr = s["hr"]
        if hr:
            hmin = min(h for h in hr if isinstance(h,(int,float)))
            hmax = max(h for h in hr if isinstance(h,(int,float)))
            hrng = (hmax-hmin) or 1.0
            poly = " ".join(
                f"{ex + (dist[i]/dmax)*ew:.1f},{ey + eh - ((hr[i]-hmin)/hrng)*eh*0.9:.1f}"
                for i in range(len(hr)) if isinstance(hr[i],(int,float)))
            svg.append(f'<polyline points="{poly}" fill="none" stroke="#5ad1e0" '
                       f'stroke-width="1.6" opacity="0.7"/>')
        svg.append(f'<text x="{ex}" y="{ey-14}" fill="#7a7a86" font-size="22" '
                   f'letter-spacing="4">ELEVATION · {int(sm.get("elevation_gain",0))} m climbed '
                   f'· <tspan fill="#5ad1e0">heart rate</tspan></text>')

    # ---- stats row ----
    stats = [
        (f'{sm.get("distance",0)/1000:.1f}', "KM"),
        (f'{int(sm.get("elevation_gain",0))}', "M CLIMB"),
        (fmt_time(sm.get("moving_time",0)), "MOVING"),
        (f'{int(max((v for v in (s["watts"] or [0]) if isinstance(v,(int,float))), default=0))}', "MAX W"),
        (f'{int(sm.get("total_calories",0))}', "CAL"),
        (f'{int(sm.get("relative_effort",0))}', "EFFORT"),
    ]
    sx = 90; sw = (W-180)/len(stats)
    for i, (big, lab) in enumerate(stats):
        x = sx + i*sw
        svg.append(f'<text x="{x:.0f}" y="1800" fill="#f4f4f6" font-size="58" '
                   f'font-weight="700">{big}</text>')
        svg.append(f'<text x="{x:.0f}" y="1838" fill="#7a7a86" font-size="22" '
                   f'letter-spacing="3">{lab}</text>')

    # ---- mantra ----
    svg.append(f'<text x="90" y="1930" fill="#3a3a44" font-size="30" '
               f'font-style="italic" letter-spacing="2">— {MANTRA}</text>')
    svg.append('</svg>')
    return "\n".join(svg)

# ----------------------------------------------------------------------------
def main():
    os.makedirs(OUT, exist_ok=True)
    ride = load_ride(RIDE_ID)
    safe = "".join(c if c.isalnum() else "_" for c in ride["name"]) or ride["id"]
    print(f"ride: {ride['name']!r}  ({ride['sport']}, {ride['start'][:10]})")
    print(f"  {ride['summary'].get('distance',0)/1000:.1f} km · "
          f"{int(ride['summary'].get('elevation_gain',0))} m climb · "
          f"effort {ride['summary'].get('relative_effort','?')}")

    print("poster ->", flush=True)
    svg = poster(ride)
    svg_path = os.path.join(OUT, safe + ".svg")
    open(svg_path, "w").write(svg)
    print("  wrote", svg_path)

    print(f"music -> ({DUR:.0f}s @ {SR}Hz, from scratch)", flush=True)
    samples, N = render(ride)
    wav_path = os.path.join(OUT, safe + ".wav")
    w = wave.open(wav_path, "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(samples.tobytes()); w.close()
    print("  wrote", wav_path, f"({N/SR:.0f}s)")
    print("\ndone. open the .svg, play the .wav.")

if __name__ == "__main__":
    main()
