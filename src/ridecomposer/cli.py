"""Command-line interface: render a ride, list rides, or build the web gallery.

    ridecomposer                       # render the newest ride (wav + svg)
    ridecomposer thurs                 # by name fragment
    ridecomposer 18879712215           # by id
    ridecomposer --list
    ridecomposer thurs -d 30 --poster-only
    ridecomposer --web --open          # gallery of all rides, opens in browser
    ridecomposer --web --streams-dir ~/rides --limit 8 -o site
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from collections.abc import Sequence

from . import __version__
from .audio import render, write_wav
from .config import Config
from .poster import build_poster
from .ride import RideNotFound, RideSource, list_rides, load_ride, resolve_source
from .web import build_web


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ridecomposer",
        description="Bike rides → generative ambient pieces, posters, and a web instrument.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("ride", nargs="?", help="ride id or name fragment (default: newest)")
    p.add_argument("-l", "--list", action="store_true", help="list available rides and exit")
    p.add_argument("--streams-dir", help="dir of <id>.json ride files (default: ./streams)")
    p.add_argument("--data-dir", help="legacy Strava export dir (activities.json + streams/)")
    p.add_argument("-n", "--limit", type=int, help="max rides to include (list / web gallery)")
    p.add_argument("-o", "--out", default="out", help="output directory (default: ./out)")
    p.add_argument("-d", "--duration", type=float, help="music length in seconds (default: 150)")
    p.add_argument("--sample-rate", type=int, help="audio sample rate (default: 32000)")
    p.add_argument("--location", help="subtitle locale on the poster")
    p.add_argument("--audio-only", action="store_true", help="render only the .wav")
    p.add_argument("--poster-only", action="store_true", help="render only the .svg")
    p.add_argument("-w", "--web", action="store_true", help="export the browser gallery (.html)")
    p.add_argument("--open", action="store_true", help="open the rendered .html in a browser")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    p.add_argument("-V", "--version", action="version", version=f"ridecomposer {__version__}")
    return p


def _print_rides(rides: list[dict]) -> None:
    if not rides:
        print("no rides found (need <id>.json files in the streams dir)", file=sys.stderr)
        return
    print(f"{'ID':<13} {'NAME':<22} {'SPORT':<13} {'DATE':<11} {'DIST':>7} {'CLIMB':>6}")
    for a in rides:
        sm = a.get("summary", {})
        print(
            f"{a.get('id', ''):<13} {str(a.get('name', ''))[:22]:<22} "
            f"{str(a.get('sport_type', ''))[:13]:<13} {str(a.get('start_local', ''))[:10]:<11} "
            f"{sm.get('distance', 0) / 1000:>6.1f}k {int(sm.get('elevation_gain', 0)):>5}m"
        )


def _default_ref(args, source: RideSource) -> str | None:
    if args.ride:
        return args.ride
    rides = list_rides(source, limit=1)
    return rides[0]["id"] if rides else None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet
    source = resolve_source(args.streams_dir, args.data_dir)

    if args.list:
        _print_rides(list_rides(source, args.limit))
        return 0

    cfg = Config().with_overrides(
        duration=args.duration,
        sample_rate=args.sample_rate,
        location=args.location,
    )

    ref = _default_ref(args, source)
    if ref is None:
        print("error: no rides found in the streams dir", file=sys.stderr)
        return 2
    try:
        ride = load_ride(ref, source)
    except RideNotFound as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    stem = os.path.join(args.out, ride.safe_name)

    if verbose:
        sm = ride.summary
        print(f"ride: {ride.name!r}  ({ride.sport}, {ride.date})")
        print(
            f"  {sm.get('distance', 0) / 1000:.1f} km · "
            f"{int(sm.get('elevation_gain', 0))} m climb · "
            f"effort {sm.get('relative_effort', '?')}"
        )

    if args.web:
        return _export_web(args, cfg, source, ride, stem, verbose)

    if not args.audio_only:
        if verbose:
            print("poster ->", flush=True)
        svg_path = stem + ".svg"
        with open(svg_path, "w", encoding="utf-8") as fh:
            fh.write(build_poster(ride, cfg))
        if verbose:
            print(f"  wrote {svg_path}")

    if not args.poster_only:
        if verbose:
            print(f"music -> ({cfg.duration:.0f}s @ {cfg.sample_rate}Hz, from scratch)", flush=True)
        samples, n = render(ride, cfg, verbose=verbose)
        wav_path = stem + ".wav"
        write_wav(wav_path, samples, cfg)
        if verbose:
            print(f"  wrote {wav_path} ({n / cfg.sample_rate:.0f}s)")

    if verbose:
        print("\ndone. open the .svg, play the .wav.")
    return 0


def _export_web(args, cfg, source, ride, stem, verbose) -> int:
    # gather up to --limit rides (newest first), ensuring the chosen one is first
    wanted = [r["id"] for r in list_rides(source, args.limit)]
    if ride.id not in wanted:
        wanted = [ride.id] + wanted[: (args.limit - 1) if args.limit else None]
    rides = []
    for rid in wanted:
        try:
            rides.append(load_ride(rid, source))
        except RideNotFound:
            continue
    rides.sort(key=lambda r: r.id != ride.id)  # chosen ride first (default card)
    html_path = stem + ".html"
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(build_web(rides, cfg, default_id=ride.id))
    if verbose:
        print(f"web -> wrote {html_path} ({len(rides)} ride(s) in the gallery)")
    if args.open:
        webbrowser.open("file://" + os.path.abspath(html_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
