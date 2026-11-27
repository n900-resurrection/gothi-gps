"""Tests of the screens of module-track/module.py (record, tracks, statistics, export, delete) with a fake recorder and made-up tracks:
python3 -m unittest discover -s tests"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "module-track"))
for cand in (os.path.join(HERE, "..", "..", "n900-gothi"), "/opt/gothi/lib"):
    if os.path.isdir(os.path.join(cand, "gothi")):
        sys.path.insert(0, cand)
        break
import tracklib as T  # noqa: E402
from gothi import keys, modules as mod  # noqa: E402
from gothi.canvas import Canvas  # noqa: E402
from gothi.dolphin import DolphinState, load_rules  # noqa: E402
from gothi.settings import Settings  # noqa: E402
from gothi.ui import Gothi  # noqa: E402
from test_tracklib import T0, fix, walk  # noqa: E402

PATH = os.path.join(HERE, "..", "module-track")
spec = importlib.util.spec_from_file_location("track_module", os.path.join(PATH, "module.py"))
tm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tm)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class Fake:
    """A recorder that is only a state file and a pid function."""

    def __init__(self):
        self.d = tempfile.mkdtemp()
        self.status = os.path.join(self.d, "status.json")
        self.running = False
        self.calls = []
        self.clock = Clock()

    def pid(self):
        return 4242 if self.running else None

    def run(self, *args):
        self.calls.append(args)
        if args[0] == "start":
            self.running = True
            T.write_status(self.status, {"running": True, "track": os.path.join(self.d, "tracks", "x.jsonl"), "started": self.clock(), "points": 0,
                                         "distance": 0.0, "mode": 0, "sv": 4, "su": 2})
        else:
            self.running = False
            st = T.read_status(self.status) or {}
            st.update(running=False)
            T.write_status(self.status, st)

    def control(self):
        return tm.Control(run=self.run, spawn=lambda f: f(), clock=self.clock, status_path=self.status, pid=self.pid)

    def tracks(self, n=2):
        folder = os.path.join(self.d, "tracks")
        for i in range(n):
            w = T.TrackWriter(os.path.join(folder, f"t{i}.jsonl"), name=f"2026-11-2{i + 1} 1{i}:30", started=T0 + i * 86400)
            for x in walk(10 + 5 * i):
                w.add(T.point(x, x["time"] + i * 86400))
            w.close()
        return folder


def make_gothi(scene, deeds=("gps_track_view", "track_recorded", "gpx_exported")):
    st = DolphinState(load_rules(extra=[{"deeds": {d: {"group": "modules", "xp": 1} for d in deeds}}]), path="")
    return Gothi(scene, Settings(os.devnull), st), st


def draw(scene, h=64):
    c = Canvas()
    c.h = h
    c.px = bytearray(c.w * h)
    g = Gothi(scene)
    g.h = h
    scene.draw(c, g)
    return c


class ManifestTest(unittest.TestCase):
    def test_valid_module(self):
        with open(os.path.join(PATH, "module.json")) as f:
            data = json.load(f)
        data["requires"] = []
        m = mod.Module(PATH, data)
        self.assertEqual((m.kind, m.menu, m.deed), ("python", "modules", "gps_track_view"))
        for d in ("gps_track_view", "track_recorded", "gpx_exported"):
            self.assertIn(d, data["deeds"])

    def test_create_makes_the_menu(self):
        class M:
            deed = "gps_track_view"
        m = tm.create(M())
        self.assertEqual([i[0] for i in m.items], ["Record", "Record with A-GPS", "Tracks"])


class ControlTest(unittest.TestCase):
    def test_start_and_stop_through_the_recorder(self):
        f = Fake()
        c = f.control()
        self.assertFalse(c.running)
        c.start()
        self.assertEqual((f.calls, c.running, c.busy), ([("start",)], True, None))
        c.start(True)                                                      # a second start is a command again, the recorder ignores it
        c.stop()
        self.assertEqual((f.calls[-1], c.running), (("stop",), False))

    def test_assisted_start_and_no_command_while_busy(self):
        f = Fake()
        c = f.control()
        c.start(True)
        self.assertEqual(f.calls, [("start", "--assisted")])
        started = []
        c.spawn = started.append
        c.start()
        c.start()
        self.assertEqual(len(started), 1)                                  # one command at a time
        c.stop()
        self.assertEqual(len(started), 1)

    def test_a_failing_command_does_not_leave_it_busy(self):
        f = Fake()
        c = f.control()
        c.run = lambda *a: 1 / 0
        with self.assertRaises(ZeroDivisionError):
            c.start()
        self.assertIsNone(c.busy)

    def test_state_is_read_once_a_second(self):
        f = Fake()
        c = f.control()
        f.running = True
        self.assertFalse(c.refresh())
        self.assertFalse(c.running)
        f.clock.t += 1.1
        self.assertTrue(c.refresh())
        self.assertTrue(c.running)


class RecordTest(unittest.TestCase):
    def test_idle_screen_and_start_stop_with_ok(self):
        f = Fake()
        ctl = f.control()
        r = tm.Record(ctl)
        g, st = make_gothi(r)
        self.assertEqual(r.lines(), ["OK = start"])
        draw(r)
        g.key(keys.OK)
        self.assertTrue(ctl.running)
        g.tick(f.clock())
        draw(r)
        self.assertIn("searching 2/4 sat", r.lines())
        g.key(keys.OK)
        self.assertFalse(ctl.running)

    def test_live_numbers(self):
        f = Fake()
        ctl = f.control()
        f.run("start")
        ctl.refresh(force=True)
        T.write_status(f.status, {"running": True, "track": "x", "started": f.clock() - 3725, "points": 41, "distance": 2340.0, "mode": 3, "sv": 9, "su": 6})
        ctl.refresh(force=True)
        r = tm.Record(ctl)
        self.assertEqual(r.lines(), ["2.34 km  41 points", "3D fix  6/9 sat"])
        for h in (64, 80):
            draw(r, h)

    def test_a_hint_after_a_minute_without_a_fix_and_an_error(self):
        f = Fake()
        ctl = f.control()
        f.run("start")
        f.clock.t += 120
        T.write_status(f.status, {"running": True, "track": "x", "started": f.clock() - 90, "points": 0, "distance": 0.0, "mode": 1, "sv": 3, "su": 0,
                                  "error": "GPS error 4"})
        ctl.refresh(force=True)
        lines = tm.Record(ctl).lines()
        self.assertIn("needs open sky", lines)
        self.assertIn("GPS error 4", lines)

    def test_the_screen_after_a_recording(self):
        f = Fake()
        T.write_status(f.status, {"running": False, "track": "x", "started": 1.0, "points": 12, "distance": 1500.0})
        ctl = f.control()
        self.assertEqual(tm.Record(ctl).lines(), ["last: 1.50 km, 12 points", "OK = start"])
        T.write_status(f.status, {"running": False, "track": None, "started": 1.0, "points": 0, "distance": 0.0})
        self.assertEqual(tm.Record(f.control()).lines(), ["last: no fix, nothing kept", "OK = start"])

    def test_a_deed_when_a_recording_with_points_ends(self):
        f = Fake()
        ctl = f.control()
        r = tm.Record(ctl)
        g, st = make_gothi(r)
        f.run("start")
        f.clock.t += 2
        g.tick(f.clock())
        T.write_status(f.status, {"running": True, "track": "x", "started": 1.0, "points": 5, "distance": 80.0, "mode": 3, "sv": 8, "su": 6})
        f.clock.t += 2
        g.tick(f.clock())
        f.run("stop")
        f.clock.t += 2
        g.tick(f.clock())
        self.assertEqual(st.xp, 1)
        f.clock.t += 2
        g.tick(f.clock())
        self.assertEqual(st.xp, 1)                                          # only once

    def test_assisted_recording_asks_first(self):
        f = Fake()
        ctl = f.control()
        r = tm.Record(ctl, assisted=True)
        g, st = make_gothi(tm.Menu("x", [("r", lambda g: r)]))
        g.key(keys.OK)
        g.key(keys.OK)
        self.assertEqual((r.asking, f.calls), (True, []))                   # nothing started: the question is shown
        draw(r)
        g.key(keys.BACK)
        self.assertEqual((r.asking, f.calls, g.top is r), (False, [], True))
        g.key(keys.OK)
        g.key(keys.OK)
        self.assertEqual(f.calls, [("start", "--assisted")])

    def test_back_leaves_and_a_tap_is_ok(self):
        f = Fake()
        ctl = f.control()
        r = tm.Record(ctl)
        root = tm.Menu("x", [("r", lambda g: r)])
        g, st = make_gothi(root)
        g.key(keys.OK)
        r.on_tap(10, 30, g)
        self.assertTrue(ctl.running)
        g.key(keys.BACK)
        self.assertIs(g.top, root)                                          # the recording goes on in the background


class TracksTest(unittest.TestCase):
    def test_list_open_statistics_and_export(self):
        f = Fake()
        folder = f.tracks()
        ctl = f.control()
        tl = tm.Tracks(ctl, folder)
        g, st = make_gothi(tl)
        self.assertEqual(len(tl.items), 2)
        self.assertTrue(tl.items[0][0].startswith("11-22 11:30"))           # the newest first
        self.assertTrue(all(len(i[0]) <= 24 for i in tl.items))
        draw(tl)
        g.key(keys.OK)
        self.assertIsInstance(g.top, tm.TrackMenu)
        g.key(keys.OK)                                                      # Statistics
        rows = g.top.rows(g)
        self.assertEqual(rows[0], "points 15")
        self.assertTrue(any(r.startswith("distance ") for r in rows))
        self.assertTrue(any(r.startswith("climbed") for r in rows))
        self.assertTrue(all(len(r) <= 21 for r in rows))
        draw(g.top)
        g.key(keys.BACK)
        g.key(keys.DOWN)
        g.key(keys.OK)                                                      # Export GPX
        self.assertEqual(g.top.__class__.__name__, "Message")
        self.assertTrue(os.path.exists(os.path.join(folder, "t1.gpx")))
        self.assertEqual(st.xp, 1)                                          # the deed of an export

    def test_no_tracks(self):
        f = Fake()
        tl = tm.Tracks(f.control(), os.path.join(f.d, "none"))
        self.assertEqual(tl.items[0][0], "none yet")
        g, st = make_gothi(tl)
        g.key(keys.OK)
        draw(g.top)

    def test_delete_asks_and_removes_the_track_and_its_gpx(self):
        f = Fake()
        folder = f.tracks()
        ctl = f.control()
        T.export_gpx(os.path.join(folder, "t1.jsonl"))
        root = tm.Menu("x", [("t", lambda g: tm.Tracks(ctl, folder))])
        g, st = make_gothi(root)
        g.key(keys.OK)
        g.key(keys.OK)                                                      # the newest track (t1)
        for _ in range(2):
            g.key(keys.DOWN)
        g.key(keys.OK)                                                      # Delete: the question
        self.assertIsInstance(g.top, tm.Confirm)
        draw(g.top)
        g.key(keys.BACK)                                                    # keep it
        self.assertTrue(os.path.exists(os.path.join(folder, "t1.jsonl")))
        g.key(keys.OK)
        g.key(keys.OK)                                                      # delete
        self.assertFalse(os.path.exists(os.path.join(folder, "t1.jsonl")))
        self.assertFalse(os.path.exists(os.path.join(folder, "t1.gpx")))
        self.assertTrue(os.path.exists(os.path.join(folder, "t0.jsonl")))
        self.assertIsInstance(g.top, tm.Tracks)
        self.assertEqual(len(g.top.items), 1)                               # the list shows what is left
        self.assertEqual(len(g.stack), 2)

    def test_a_track_that_is_being_recorded_is_not_deleted_or_exported(self):
        f = Fake()
        folder = f.tracks(1)
        ctl = f.control()
        f.running = True
        T.write_status(f.status, {"running": True, "track": os.path.join(folder, "t0.jsonl"), "started": 1.0, "points": 3, "distance": 10.0})
        ctl.refresh(force=True)
        t = T.list_tracks(folder)[0]
        tmenu = tm.TrackMenu(ctl, t)
        g, st = make_gothi(tmenu)
        g.key(keys.DOWN)
        g.key(keys.OK)
        self.assertEqual(g.top.__class__.__name__, "Message")
        self.assertFalse(os.path.exists(os.path.join(folder, "t0.gpx")))
        g.key(keys.BACK)
        g.key(keys.DOWN)
        g.key(keys.OK)
        conf = g.top
        g.key(keys.OK)
        self.assertTrue(os.path.exists(os.path.join(folder, "t0.jsonl")))
        self.assertIsNot(g.top, conf)

    def test_statistics_of_a_track_without_points(self):
        f = Fake()
        p = os.path.join(f.d, "tracks", "e.jsonl")
        T.TrackWriter(p, name="E", started=T0).close()
        s = tm.Stats({"path": p, "name": "E"})
        self.assertEqual(s.rows(Gothi(s))[:3], ["points 0", "distance 0 m", "time 0:00:00"])
        draw(s)


if __name__ == "__main__":
    unittest.main()
