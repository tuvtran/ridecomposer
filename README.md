# ridecomposer

Feed it one real bike ride; it renders two artifacts, both procedurally driven
by the ride's actual data:

- **`out/<name>.wav`** — a ~2.5-minute generative **ambient** piece. The ride's
  effort curve *is* the song's form: the climb is the build, the redline is the
  drop, the descent is release. The rider's heart rate is the literal pulse.
- **`out/<name>.svg`** — a printable **poster**: the route, glowing hot where
  the rider suffered; the elevation profile; the stats.

Everything — every oscillator, envelope, the reverb, the polyline decode, the
map projection — is written from scratch in the **pure Python standard library**.
No numpy, no scipy, no audio library, no plotting library. That constraint is the
point.

```
suffer with purpose
```

## Quickstart

```sh
uv run ridecomposer            # render the newest ride -> out/thurs.wav + out/thurs.svg
uv run ridecomposer --list     # rides found in ./streams (or bundled)
uv run ridecomposer bikes      # render by name fragment
uv run ridecomposer 18803276852 -d 30   # by id, 30-second sketch
uv run ridecomposer --web --open         # the browser gallery + instruments
```

Rides live in a **`streams/` folder** — one self-contained `<id>.json` per ride
(each carries its own streams, summary, and route polyline). Three ship inside
the package, so it runs with zero setup. A full render of the default 150 s piece
takes ~20 s in pure Python (it prints progress). Use `-d`/`--duration` for a
quick sketch.

No `uv`? `python3 compose.py thurs` works too.

## Browser: gallery + ride-along instrument

```sh
uv run ridecomposer --web --open                 # gallery of all rides
uv run ridecomposer --web --limit 8 --streams-dir ~/rides -o site   # pick a folder + cap
```

`--web` exports a single **self-contained HTML file** — no server, no deps, opens
on a double-click. It lands on a **gallery**: a card per composed ride with its
route thumbnail and stats. Click one to enter its *ride-along instrument*, where
the piece is synthesized live via the Web Audio API as the route draws hot and
the climb builds. `← gallery` goes back.

A **genre / speed** control morphs the piece across three tempos, each adding its
own layers on a BPM grid — all still driven by the ride's effort:

| Speed   | Genre       | What you get                                               |
|---------|-------------|------------------------------------------------------------|
| `1:00`  | techno      | 140 BPM four-on-the-floor kick, open hats, acid bass, hard |
| `2:00`  | house       | 124 BPM swung groove, warmer pads, rolling bass            |
| `4:00`  | downtempo   | no kick — the original ambient: drone, bells, real heartbeat |

Plus live mix sliders: reverb, *suffering* (shimmer amount), volume. The browser
engine mirrors the offline mappings (drone opens with power, shimmer gates in on
the climbs, the heartbeat tracks real HR) but synthesizes in realtime with Web
Audio nodes. The offline `.wav` stays the downtempo master.

## CLI

```
ridecomposer [RIDE] [options]

  RIDE                ride id or name fragment (default: newest)
  -l, --list          list available rides and exit
  --streams-dir PATH  dir of <id>.json ride files (default: ./streams or bundled)
  --data-dir PATH     legacy Strava export dir (activities.json + streams/)
  -n, --limit N       max rides to include (list / web gallery)
  -o, --out PATH      output directory (default: ./out)
  -d, --duration SEC  music length in seconds (default: 150)
  --sample-rate SR    audio sample rate (default: 32000)
  --location NAME     subtitle locale on the poster
  --audio-only        render only the .wav
  --poster-only       render only the .svg
  -w, --web           export the browser gallery (.html)
  --open              open the rendered .html in a browser
  -q, --quiet         suppress progress
  -V, --version
```

### Composing your own rides

A ride is one self-contained file `streams/<id>.json` carrying its `streams`,
`summary`, and `reduced_polyline`. Drop more files into `./streams` (or any
folder you point `--streams-dir`/`$RIDECOMPOSER_STREAMS` at) and they show up:

```sh
ridecomposer --list --streams-dir ~/rides
ridecomposer --web --streams-dir ~/rides --limit 12 -o site
```

A **legacy Strava export** (an `activities.json` plus a `streams/` subdir) also
works via `--data-dir` — the activity record fills in summary/polyline.

Resolution order: `--streams-dir` → `--data-dir` → `$RIDECOMPOSER_STREAMS` →
`$RIDECOMPOSER_DATA` → `./streams` → the bundled samples.

## The mapping (data → sound)

The whole point is a *reading of this effort*, not generic sonification. Harder
effort = the sound opens up and gets heavier; the heartbeat is real.

| Layer        | Driven by            | Behavior                                                        |
|--------------|----------------------|-----------------------------------------------------------------|
| **drone**    | power                | root + fifth; timbre crossfades dark→bright as effort rises      |
| **pad**      | power                | minor triad an octave up; amplitude swells with effort           |
| **shimmer**  | power (gated)        | high detuned cluster, only above threshold — the audible suffering |
| **heartbeat**| heart rate           | sub thump at HR/2 in music-time; quickens and weights with HR    |
| **bells**    | altitude + cadence   | pitch register from altitude (climb→higher); rate from cadence   |
| **space**    | —                    | from-scratch stereo cross-feedback delay with a damped loop      |
| stereo field | grade + altitude     | climb leans left, descent right; widened by altitude             |

Key is A minor pentatonic (consonant by construction). Musical time maps linearly
onto ride-elapsed time, so the song's pacing is the shape of the ride.

**All the knobs live in [`config.py`](src/ridecomposer/config.py)** — the taste
layer. Change a value, re-render, hear a different reading. It's deterministic
(an integer hash seeds all variation), so every render reproduces exactly.

## Layout

```
streams/       your ride files (<id>.json, self-contained) — drop more in here
src/ridecomposer/
  config.py    the taste layer — every mapping knob
  ride.py      ride loading from a streams dir, samplers, polyline decode
  dsp.py       from-scratch primitives: wavetables, hash, soft-clip, feedback delay
  audio.py     the offline render engine (drone / pad / shimmer / heartbeat / bells)
  poster.py    the SVG poster (projection, heat ramp, elevation ribbon, stats)
  web.py       exporter: inline rides into the browser gallery
  cli.py       argparse CLI
  _rides/      the three bundled sample rides (for zero-setup / uv tool install)
  _web/        the gallery + realtime Web Audio instrument (HTML template)
reference/
  compose.py   the original single-file vibecode, kept verbatim for provenance
tests/
```

## Develop

```sh
uv sync          # create the venv (zero runtime deps; pytest + ruff for dev)
uv run pytest    # fast deterministic smoke tests
uv run ruff check src tests
```

## Where it grows

- **MIDI export** → shape the piece with real instruments in Ableton ("Phase 0").
- **Realtime** → live BLE power/HR into the same engine, reacting in the pain cave.
- **Meditation mode** → breath / HRV coherence → calm generative ambient + visuals.

---

*Built from a brief. The DSP is from scratch on purpose — that's where the
satisfaction and the learning live.*
