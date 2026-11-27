"""Tests of module-track/tracklib.py with a made-up route (a walk north-east of a point that is not a real place):  python3 -m unittest discover -s tests"""
import json
import math
import os
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "module-track"))
import tracklib as T  # noqa: E402

T0 = 1732700000.0


def fix(lat=50.0, lon=14.0, mode=3, eph=8.0, t=T0, alt=240.0, speed=5.0):
    return {"mode": mode, "lat": lat, "lon": lon, "alt": alt, "speed": speed, "course": 45.0, "eph": eph, "time": t, "sv": 9, "su": 5}


def walk(n=20, step=0.0001, dt=3.0):
    """n fixes about 11 m apart (0.0001 degrees of latitude), dt seconds apart, climbing a metre a step."""
    return [fix(50.0 + i * step, 14.0 + i * step / 2, t=T0 + i * dt, alt=240.0 + i, speed=14.0) for i in range(n)]


class ParseTest(unittest.TestCase):
    def test_fix_line(self):
        p = T.parse_raw("FIX 3 49.1234567 16.1234567 232.1 3.20 90.0 12.0 1732700000 9 5")
        self.assertEqual((p["mode"], p["lat"], p["lon"], p["alt"], p["speed"], p["course"], p["eph"], p["time"], p["sv"], p["su"]),
                         (3, 49.1234567, 16.1234567, 232.1, 3.2, 90.0, 12.0, 1732700000.0, 9, 5))

    def test_no_fix_and_unknown_values(self):
        p = T.parse_raw("FIX 1 nan nan nan nan nan nan nan 3 0")
        self.assertEqual((p["mode"], p["lat"], p["su"]), (1, None, 0))
        p = T.parse_raw("FIX 2 50.0 14.0 nan nan nan nan nan 4 3")
        self.assertIsNone(p["alt"])

    def test_error_and_garbage(self):
        self.assertEqual(T.parse_raw("ERR 4"), {"err": "4"})
        for bad in ("", None, "hello", "FIX 3 1 2", "FIX x 1 2 3 4 5 6 7 8 9", "FIX 3 nan nan 1 2 3 4 5 6 7", "FIX 3 95.0 14.0 1 2 3 4 5 6 7",
                    "FIX 3 50.0 190.0 1 2 3 4 5 6 7", "Starting GPS..."):
            self.assertIsNone(T.parse_raw(bad), bad)


class DistanceTest(unittest.TestCase):
    def test_known_distances(self):
        a, b = {"lat": 50.0, "lon": 14.0}, {"lat": 50.001, "lon": 14.0}
        self.assertAlmostEqual(T.distance(a, b), 111.2, delta=0.5)                       # a thousandth of a degree of latitude
        self.assertEqual(T.distance(a, a), 0.0)
        east = {"lat": 50.0, "lon": 14.001}
        self.assertAlmostEqual(T.distance(a, east), 111.2 * math.cos(math.radians(50)), delta=0.5)
        self.assertAlmostEqual(T.distance({"lat": 0, "lon": 0}, {"lat": 0, "lon": 180}), math.pi * 6371000, delta=1)


class FilterTest(unittest.TestCase):
    def test_first_fix_is_kept_and_a_fix_without_position_is_not(self):
        f = T.Filter()
        self.assertFalse(f.accept(fix(mode=1, t=T0), T0))
        self.assertFalse(f.accept(None, T0))
        self.assertFalse(f.accept({"mode": 3, "lat": None}, T0))
        self.assertTrue(f.accept(fix(), T0))

    def test_close_and_quick_fixes_are_dropped(self):
        f = T.Filter()
        f.accept(fix(), T0)
        self.assertFalse(f.accept(fix(lat=50.00002), T0 + 3))                             # 2 m away
        self.assertFalse(f.accept(fix(lat=50.0002), T0 + 1))                              # 22 m but one second
        self.assertTrue(f.accept(fix(lat=50.0002), T0 + 3))

    def test_heartbeat_when_standing_still(self):
        f = T.Filter()
        f.accept(fix(), T0)
        self.assertFalse(f.accept(fix(), T0 + 20))
        self.assertTrue(f.accept(fix(), T0 + T.HEARTBEAT))

    def test_inexact_and_impossible_fixes_are_dropped(self):
        f = T.Filter()
        self.assertFalse(f.accept(fix(eph=T.MAX_ERROR + 1), T0))
        self.assertTrue(f.accept(fix(eph=None), T0))                                      # unknown error is accepted
        self.assertFalse(f.accept(fix(lat=51.0), T0 + 10))                                # 111 km in 10 s
        self.assertFalse(f.accept(fix(lat=50.0005), T0))                                  # the clock did not move on
        self.assertTrue(f.accept(fix(lat=50.0005), T0 + 10))

    def test_a_walk_is_kept_almost_whole(self):
        f = T.Filter()
        kept = [x for x in walk() if f.accept(x, x["time"])]
        self.assertEqual(len(kept), 20)


class PointTest(unittest.TestCase):
    def test_point_record(self):
        p = T.point(fix(alt=None, speed=None, eph=None), T0)
        self.assertEqual(p, {"t": T0, "lat": 50.0, "lon": 14.0, "m": 3, "sat": 5, "co": 45.0})
        p = T.point(fix(), T0)
        self.assertEqual((p["ele"], p["sp"], p["eph"]), (240.0, 5.0, 8.0))


class FileTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.path = os.path.join(self.d, "tracks", "t.jsonl")

    def write(self, n=10):
        w = T.TrackWriter(self.path, name="Morning walk", started=T0)
        for x in walk(n):
            w.add(T.point(x, x["time"]))
        w.close()

    def test_write_and_read_back(self):
        self.write()
        header, pts = T.read_track(self.path)
        self.assertEqual((header["name"], header["started"], header["v"], header["app"]), ("Morning walk", T0, 1, "gothi-gps"))
        self.assertEqual(len(pts), 10)
        self.assertEqual(pts[3]["lat"], 50.0003)

    def test_appending_does_not_write_a_second_header(self):
        self.write(3)
        w = T.TrackWriter(self.path)
        w.add(T.point(walk(4)[3], T0 + 99))
        w.close()
        header, pts = T.read_track(self.path)
        self.assertEqual(len(pts), 4)
        with open(self.path) as f:
            self.assertEqual(sum(1 for ln in f if '"v":1' in ln), 1)

    def test_a_half_written_last_line_and_garbage_are_skipped(self):
        self.write(5)
        with open(self.path, "a") as f:
            f.write('{"t":1,"lat":50.0,"lo')                                              # the power went
        _, pts = T.read_track(self.path)
        self.assertEqual(len(pts), 5)
        with open(os.path.join(self.d, "junk.jsonl"), "w") as f:
            f.write("hello\n[1, 2]\n42\n")
        self.assertEqual(T.read_track(os.path.join(self.d, "junk.jsonl")), ({}, []))
        self.assertEqual(T.read_track(os.path.join(self.d, "missing")), ({}, []))

    def test_list_tracks_newest_first_and_delete(self):
        for i, t in enumerate((T0, T0 + 5000, T0 + 100)):
            w = T.TrackWriter(os.path.join(self.d, "tracks", f"t{i}.jsonl"), name=f"n{i}", started=t)
            w.add(T.point(fix(), t))
            w.close()
        names = [t["name"] for t in T.list_tracks(os.path.join(self.d, "tracks"))]
        self.assertEqual(names, ["n1", "n2", "n0"])
        self.assertEqual(T.list_tracks(os.path.join(self.d, "none")), [])
        p = os.path.join(self.d, "tracks", "t1.jsonl")
        T.export_gpx(p)
        self.assertEqual(T.delete_track(p), 2)
        self.assertEqual(T.delete_track(p), 0)
        self.assertEqual(len(T.list_tracks(os.path.join(self.d, "tracks"))), 2)


class StatsTest(unittest.TestCase):
    def pts(self, n=20):
        return [T.point(x, x["time"]) for x in walk(n)]

    def test_empty_and_single(self):
        self.assertEqual(T.stats([])["points"], 0)
        s = T.stats(self.pts(1))
        self.assertEqual((s["points"], s["distance"], s["duration"]), (1, 0.0, 0.0))

    def test_walk(self):
        s = T.stats(self.pts(20))
        self.assertEqual(s["points"], 20)
        self.assertAlmostEqual(s["distance"], 19 * 11.1 * math.hypot(1, 0.5 * math.cos(math.radians(50))), delta=8)
        self.assertEqual(s["duration"], 57.0)
        self.assertAlmostEqual(s["avg"], s["distance"] / 57 * 3.6, delta=0.01)
        self.assertEqual((s["low"], s["high"]), (240.0, 259.0))
        self.assertEqual(s["ascent"], 18.0)                                               # 19 m up, counted in steps of 3 m: the last metre is not yet a step
        self.assertEqual((s["start"], s["end"]), (T0, T0 + 57))

    def test_ascent_ignores_jitter(self):
        pts = [T.point(fix(alt=240 + (i % 2), lat=50 + i * 1e-4, t=T0 + i * 3), T0 + i * 3) for i in range(20)]
        self.assertEqual(T.stats(pts)["ascent"], 0.0)

    def test_top_speed_from_the_reported_speed(self):
        pts = self.pts(5)
        pts[2]["sp"] = 33.0
        self.assertEqual(T.stats(pts)["max"], 33.0)

    def test_without_altitude(self):
        pts = [T.point(fix(alt=None, lat=50 + i * 1e-4, t=T0 + i * 3), T0 + i * 3) for i in range(5)]
        s = T.stats(pts)
        self.assertEqual((s["low"], s["high"], s["ascent"]), (None, None, 0.0))


class GpxTest(unittest.TestCase):
    NS = {"g": "http://www.topografix.com/GPX/1/1"}

    def test_gpx_is_valid_xml_in_schema_order(self):
        pts = [T.point(x, x["time"]) for x in walk(6)]
        root = ET.fromstring(T.gpx({"name": "Walk <1> & \"co\""}, pts))
        self.assertEqual(root.tag, "{http://www.topografix.com/GPX/1/1}gpx")
        self.assertEqual(root.get("version"), "1.1")
        self.assertEqual(root.find("g:trk/g:name", self.NS).text, 'Walk <1> & "co"')
        trkpts = root.findall("g:trk/g:trkseg/g:trkpt", self.NS)
        self.assertEqual(len(trkpts), 6)
        self.assertEqual([c.tag.split("}")[1] for c in trkpts[0]], ["ele", "time", "fix", "sat"])
        self.assertEqual((trkpts[1].get("lat"), trkpts[1].get("lon")), ("50.0001000", "14.0000500"))
        self.assertEqual(trkpts[0].find("g:time", self.NS).text, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0)))
        self.assertEqual(root.find("g:metadata/g:time", self.NS).text, trkpts[0].find("g:time", self.NS).text)

    def test_two_d_fix_and_no_altitude(self):
        p = T.point(fix(mode=2, alt=None), T0)
        root = ET.fromstring(T.gpx({}, [p]))
        pt = root.find("g:trk/g:trkseg/g:trkpt", self.NS)
        self.assertEqual([c.tag.split("}")[1] for c in pt], ["time", "fix", "sat"])
        self.assertEqual(pt.find("g:fix", self.NS).text, "2d")
        self.assertEqual(root.find("g:trk/g:name", self.NS).text, "track")                # a track without a name gets one

    def test_export_writes_next_to_the_track_and_refuses_an_empty_one(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "a.jsonl")
        w = T.TrackWriter(path, name="A", started=T0)
        w.close()
        self.assertIsNone(T.export_gpx(path))
        self.assertFalse(os.path.exists(os.path.join(d, "a.gpx")))
        w = T.TrackWriter(path)
        w.add(T.point(fix(), T0))
        w.close()
        self.assertEqual(T.export_gpx(path), os.path.join(d, "a.gpx"))
        ET.parse(os.path.join(d, "a.gpx"))
        self.assertFalse(os.path.exists(os.path.join(d, "a.gpx.tmp")))


class FormatTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual((T.fmt_dist(0), T.fmt_dist(812.4), T.fmt_dist(2340)), ("0 m", "812 m", "2.34 km"))
        self.assertEqual((T.fmt_dur(0), T.fmt_dur(65), T.fmt_dur(3725)), ("0:00:00", "0:01:05", "1:02:05"))
        self.assertRegex(T.track_name(T0), r"^\d{4}-\d\d-\d\d \d\d:\d\d$")
        self.assertRegex(T.file_name(T0), r"^track-\d{8}-\d{6}$")

    def test_status_file(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x", "s.json")
        self.assertIsNone(T.read_status(p))
        T.write_status(p, {"running": True, "points": 3})
        self.assertEqual(T.read_status(p), {"running": True, "points": 3})
        with open(p, "w") as f:
            f.write("[1]")
        self.assertIsNone(T.read_status(p))
        with open(p, "w") as f:
            f.write("{")
        self.assertIsNone(T.read_status(p))


if __name__ == "__main__":
    unittest.main()
