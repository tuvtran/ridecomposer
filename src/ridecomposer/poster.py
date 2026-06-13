"""The visual engine: a printable SVG poster, drawn from scratch.

The route, projected and colored so it glows hot where the rider suffered; the
elevation profile with the effort ridge and a cool HR line; the stats. Dark,
minimal, gallery-like. Plain text SVG — renders in any browser or Obsidian.
"""

from __future__ import annotations

import math

from .config import DEFAULT, Config
from .ride import Ride, decode_polyline, sampler
from .util import NUMBER, clamp, lerp, normalizer

# inferno-ish ramp: black -> purple -> red -> orange -> pale yellow (heat = effort)
_RAMP = [
    (0.00, (8, 4, 18)),
    (0.25, (66, 10, 104)),
    (0.50, (147, 38, 103)),
    (0.75, (221, 81, 58)),
    (0.90, (252, 165, 10)),
    (1.00, (252, 255, 164)),
]


def _heat(x: float) -> tuple[int, int, int]:
    x = clamp(x)
    for j in range(len(_RAMP) - 1):
        a, ca = _RAMP[j]
        b, cb = _RAMP[j + 1]
        if x <= b:
            f = (x - a) / (b - a) if b > a else 0.0
            return tuple(int(lerp(ca[k], cb[k], f)) for k in range(3))
    return _RAMP[-1][1]


def _rgb(c: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)


def _fmt_time(sec: float) -> str:
    sec = int(sec)
    h, m = sec // 3600, (sec % 3600) // 60
    return f"{h}:{m:02d}" if h else f"{m}:{sec % 60:02d}"


def build_poster(ride: Ride, cfg: Config = DEFAULT) -> str:
    w, h = cfg.poster_w, cfg.poster_h
    s = ride.streams
    sm = ride.summary
    times = s["time"]
    f_pow = sampler(times, s["watts"])
    n_pow = normalizer(s["watts"]) if s["watts"] else (lambda _x: 0.3)
    t0, t1 = (times[0], times[-1]) if times else (0.0, 1.0)
    pts = decode_polyline(ride.polyline)

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="Helvetica Neue, Arial, sans-serif">',
        f'<rect width="{w}" height="{h}" fill="#0a0a0e"/>',
        '<defs><filter id="glow" x="-20%" y="-20%" width="140%" height="140%">'
        '<feGaussianBlur stdDeviation="6" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
        "</filter></defs>",
    ]

    # ---- title ----
    name = ride.name.upper()
    locale = cfg.location.upper().strip()
    subtitle = " · ".join(x for x in (ride.date, locale, ride.sport.upper()) if x)
    svg.append(
        f'<text x="90" y="150" fill="#f4f4f6" font-size="92" '
        f'font-weight="700" letter-spacing="6">{_xml(name)}</text>'
    )
    svg.append(
        f'<text x="94" y="200" fill="#7a7a86" font-size="30" '
        f'letter-spacing="10">{_xml(subtitle)}</text>'
    )

    # ---- route map, colored by effort ----
    if pts:
        _route(svg, pts, w, f_pow, n_pow, t0, t1)

    # ---- elevation ribbon ----
    _elevation(svg, s, sm, w, f_pow, n_pow, times)

    # ---- stats row ----
    max_w = int(max((v for v in (s["watts"] or [0]) if isinstance(v, NUMBER)), default=0))
    stats = [
        (f'{sm.get("distance", 0) / 1000:.1f}', "KM"),
        (f'{int(sm.get("elevation_gain", 0))}', "M CLIMB"),
        (_fmt_time(sm.get("moving_time", 0)), "MOVING"),
        (f"{max_w}", "MAX W"),
        (f'{int(sm.get("total_calories", 0))}', "CAL"),
        (f'{int(sm.get("relative_effort", 0))}', "EFFORT"),
    ]
    sx = 90
    sw = (w - 180) / len(stats)
    for i, (big, lab) in enumerate(stats):
        x = sx + i * sw
        svg.append(
            f'<text x="{x:.0f}" y="1800" fill="#f4f4f6" font-size="58" '
            f'font-weight="700">{big}</text>'
        )
        svg.append(
            f'<text x="{x:.0f}" y="1838" fill="#7a7a86" font-size="22" '
            f'letter-spacing="3">{lab}</text>'
        )

    # ---- mantra ----
    svg.append(
        f'<text x="90" y="1930" fill="#3a3a44" font-size="30" '
        f'font-style="italic" letter-spacing="2">— {_xml(cfg.mantra)}</text>'
    )
    svg.append("</svg>")
    return "\n".join(svg)


def _route(svg, pts, w, f_pow, n_pow, t0, t1):
    mlat = sum(p[0] for p in pts) / len(pts)
    kx = math.cos(math.radians(mlat))  # equirectangular: squeeze lng to fix aspect
    xs = [p[1] * kx for p in pts]
    ys = [p[0] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    rw = (x1 - x0) or 1e-6
    rh = (y1 - y0) or 1e-6
    bx, by, bw, bh = 90, 280, w - 180, 1060
    scale = min(bw / rw, bh / rh)
    ox = bx + (bw - rw * scale) / 2
    oy = by + (bh - rh * scale) / 2

    def proj(la, lo):
        return ox + (lo * kx - x0) * scale, oy + (y1 - la) * scale

    # cumulative length -> progress, to look up effort along the route
    cum = [0.0]
    for k in range(1, len(pts)):
        cum.append(cum[-1] + math.dist(pts[k], pts[k - 1]))
    total = cum[-1] or 1.0

    for k in range(1, len(pts)):
        xa, ya = proj(*pts[k - 1])
        xb, yb = proj(*pts[k])
        e = n_pow(f_pow(lerp(t0, t1, cum[k] / total)))
        col = _rgb(_heat(e))
        wdt = 2.5 + 6.0 * e
        svg.append(
            f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" '
            f'stroke="{col}" stroke-width="{wdt:.1f}" stroke-linecap="round" '
            f'opacity="0.92" filter="url(#glow)"/>'
        )
    sx, sy = proj(*pts[0])
    svg.append(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="9" fill="#f4f4f6"/>')


def _elevation(svg, s, sm, w, f_pow, n_pow, times):
    ex, ey, ew, eh = 90, 1380, w - 180, 300
    alt = s["altitude"]
    dist = s["distance"]
    if not (alt and dist):
        return
    amin = min(a for a in alt if isinstance(a, NUMBER))
    amax = max(a for a in alt if isinstance(a, NUMBER))
    dmax = max(d for d in dist if isinstance(d, NUMBER)) or 1.0
    # floor the altitude range so a flat ride's sensor jitter doesn't blow up into spikes
    arng = max(amax - amin, 55.0)

    def ept(i):
        x = ex + (dist[i] / dmax) * ew
        y = ey + eh - ((alt[i] - amin) / arng) * eh
        return x, y

    # filled silhouette
    path = f"M {ex} {ey + eh} "
    for i in range(len(alt)):
        x, y = ept(i)
        path += f"L {x:.1f} {y:.1f} "
    path += f"L {ex + ew} {ey + eh} Z"
    svg.append(f'<path d="{path}" fill="#16161e"/>')

    # effort-colored ridge
    for i in range(1, len(alt)):
        xa, ya = ept(i - 1)
        xb, yb = ept(i)
        e = n_pow(f_pow(times[i])) if i < len(times) else 0.3
        svg.append(
            f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" '
            f'stroke="{_rgb(_heat(e))}" stroke-width="4"/>'
        )

    # cool HR overlay
    hr = s["hr"]
    if hr:
        hmin = min(v for v in hr if isinstance(v, NUMBER))
        hmax = max(v for v in hr if isinstance(v, NUMBER))
        hrng = (hmax - hmin) or 1.0
        poly = " ".join(
            f"{ex + (dist[i] / dmax) * ew:.1f},{ey + eh - ((hr[i] - hmin) / hrng) * eh * 0.9:.1f}"
            for i in range(min(len(hr), len(dist)))
            if isinstance(hr[i], NUMBER)
        )
        svg.append(
            f'<polyline points="{poly}" fill="none" stroke="#5ad1e0" '
            f'stroke-width="1.6" opacity="0.7"/>'
        )
    svg.append(
        f'<text x="{ex}" y="{ey - 14}" fill="#7a7a86" font-size="22" letter-spacing="4">'
        f'ELEVATION · {int(sm.get("elevation_gain", 0))} m climbed '
        f'· <tspan fill="#5ad1e0">heart rate</tspan></text>'
    )


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
