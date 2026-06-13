"""Fast, deterministic smoke tests. Short renders so the suite stays snappy."""

from __future__ import annotations

import wave

import pytest

from ridecomposer.audio import render, write_wav
from ridecomposer.config import Config
from ridecomposer.poster import build_poster
from ridecomposer.ride import RideNotFound, decode_polyline, list_rides, load_ride, resolve_source
from ridecomposer.web import build_web

# small + fast: 2s at 16k still exercises every layer
FAST = Config(duration=2.0, sample_rate=16_000)


@pytest.fixture(scope="module")
def source():
    return resolve_source()


@pytest.fixture(scope="module")
def hero(source):
    return load_ride("thurs", source)


def test_bundled_rides_present(source):
    rides = list_rides(source)
    ids = {str(r["id"]) for r in rides}
    assert "18879712215" in ids  # the hero
    assert len(rides) >= 3


def test_rides_sorted_newest_first(source):
    rides = list_rides(source)
    dates = [r["start_local"] for r in rides]
    assert dates == sorted(dates, reverse=True)


def test_limit(source):
    assert len(list_rides(source, limit=2)) == 2


def test_resolve_by_name_and_id(source):
    assert load_ride("18879712215", source).id == "18879712215"
    assert load_ride("thurs", source).id == "18879712215"


def test_self_contained_ride_has_summary_and_route(hero):
    assert hero.summary.get("distance", 0) > 0
    assert hero.polyline  # the ride file carries its own polyline


def test_unknown_ride_raises(source):
    with pytest.raises(RideNotFound):
        load_ride("definitely-not-a-ride", source)


def test_decode_polyline_known_value():
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert len(pts) == 3
    assert pts[0] == pytest.approx((38.5, -120.2), abs=1e-4)
    assert pts[2] == pytest.approx((43.252, -126.453), abs=1e-4)


def test_render_produces_valid_stereo_wav(hero, tmp_path):
    samples, frames = render(hero, FAST, verbose=False)
    assert frames == int(FAST.duration * FAST.sample_rate)
    assert len(samples) == frames * 2  # interleaved stereo
    path = tmp_path / "t.wav"
    write_wav(str(path), samples, FAST)
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 2
        assert w.getframerate() == FAST.sample_rate
        assert w.getnframes() == frames


def test_render_is_deterministic(hero):
    a, _ = render(hero, FAST, verbose=False)
    b, _ = render(hero, FAST, verbose=False)
    assert a.tobytes() == b.tobytes()


def test_heartbeat_is_audible(hero):
    samples, _ = render(hero, FAST, verbose=False)
    assert max(abs(x) for x in samples) > 1000


def test_web_export_is_self_contained(hero, source):
    rides = [load_ride(str(r["id"]), source) for r in list_rides(source)]
    html = build_web(rides, FAST, default_id=hero.id)
    assert html.startswith("<!doctype html>")
    assert "__RIDECOMPOSER_DATA__" not in html  # data token substituted
    assert hero.id in html
    assert "AudioContext" in html  # realtime engine inlined
    assert "GENRES" in html  # genre engine present
    assert html.rstrip().endswith("</html>")


def test_poster_has_stats_and_name(hero):
    svg = build_poster(hero, FAST)
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert "THURS" in svg
    assert "KM" in svg and "EFFORT" in svg
    assert "suffer with purpose" in svg
