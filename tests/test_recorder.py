"""Tests of module-track/recorder.py: the real background process (fork, a pid file, SIGTERM) with a fake GPS helper that prints made-up fixes:
python3 -m unittest discover -s tests"""
import importlib.util
import os
import shutil
import sys
import tempfile
import textwrap
import time
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "module-track"))
import tracklib as T  # noqa: E402

PATH = os.path.join(HERE, "..", "module-track", "recorder.py")
T0 = 1732700000

# the fake helper: three lines without a fix, then a walk north-east (about 11 m and 3 s of GPS time a step), then it just waits
WALK = textwrap.dedent("""
    import sys, time
    for i in range(3):
        print("FIX 1 nan nan nan nan nan nan nan %d 0" % i); sys.stdout.flush(); time.sleep(0.05)
    for i in range(12):
        print("FIX 3 %.7f %.7f %.1f 5.00 45.0 8.0 %d 9 5" % (50.0 + i * 0.0001, 14.0 + i * 0.00005, 240 + i, __T0__ + i * 3)); sys.stdout.flush(); time.sleep(0.05)
    time.sleep(60)
""").replace("__T0__", str(T0))
NOFIX = textwrap.dedent("""
    import sys, time
    while True:
        print("FIX 1 nan nan nan nan nan nan nan 2 0"); sys.stdout.flush(); time.sleep(0.05)
""")
ERROR = textwrap.dedent("""
    import sys, time
    print("ERR 4"); sys.stdout.flush(); time.sleep(60)
""")
EXIT = "import sys; sys.exit(0)\n"


class RecorderTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ["GOTHI_TRACK_DIR"] = os.path.join(self.d, "tracks")
        os.environ["GOTHI_STATE_DIR"] = os.path.join(self.d, "state")
        spec = importlib.util.spec_from_file_location("recorder_under_test", PATH)
        self.r = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.r)
        self.r.MARK = b"python"                          # the forked process has the command line of this test run

    def tearDown(self):
        self.r.stop()
        os.environ.pop("GOTHI_GPS_CMD", None)
        shutil.rmtree(self.d, ignore_errors=True)

    def source(self, code):
        p = os.path.join(self.d, "fake.py")
        with open(p, "w") as f:
            f.write(code)
        os.environ["GOTHI_GPS_CMD"] = f"{sys.executable} {p}"

    def wait(self, cond, seconds=10):
        end = time.time() + seconds
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def status(self):
        return T.read_status(self.r.STATUS) or {}

    def test_records_a_walk_and_exports_gpx_on_stop(self):
        self.source(WALK)
        self.assertEqual(self.r.start(), 0)
        self.assertIsNotNone(self.r.read_pid())
        self.assertEqual(self.r.main(["recorder.py", "status"]), 0)
        self.assertTrue(self.wait(lambda: self.status().get("points", 0) >= 12))
        st = self.status()
        self.assertEqual((st["running"], st["mode"], st["sv"], st["su"]), (True, 3, 9, 5))
        self.assertAlmostEqual(st["distance"], 11 * 12.4, delta=10)
        self.assertEqual(self.r.start(), 0)                                  # a second start changes nothing
        self.r.stop()
        self.assertIsNone(self.r.read_pid())
        st = self.status()
        self.assertFalse(st["running"])
        self.assertTrue(st["gpx"].endswith(".gpx"))
        header, pts = T.read_track(st["track"])
        self.assertEqual(len(pts), 12)
        self.assertEqual(pts[0]["lat"], 50.0)
        root = ET.parse(st["gpx"]).getroot()
        self.assertEqual(len(root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")), 12)

    def test_no_fix_leaves_no_track(self):
        self.source(NOFIX)
        self.assertEqual(self.r.start(), 0)
        self.assertTrue(self.wait(lambda: self.status().get("sv") == 2))
        self.assertEqual(self.status()["mode"], 1)
        self.r.stop()
        st = self.status()
        self.assertEqual((st["running"], st["points"], st["track"], st["gpx"]), (False, 0, None, None))
        self.assertEqual(T.list_tracks(self.r.TRACK_DIR), [])
        self.assertEqual([n for n in os.listdir(self.r.TRACK_DIR)], [])

    def test_a_gps_error_is_reported_and_cleared(self):
        self.source(ERROR)
        self.assertEqual(self.r.start(), 0)
        self.assertTrue(self.wait(lambda: self.status().get("error") == "GPS error 4"))

    def test_the_helper_ending_stops_the_recorder(self):
        self.source(EXIT)
        self.r.start()
        self.assertTrue(self.wait(lambda: self.r.read_pid() is None and not self.status().get("running", True)))
        self.assertEqual(self.status()["error"], "the GPS helper ended")

    def test_a_missing_helper_is_not_a_start(self):
        os.environ["GOTHI_GPS_CMD"] = "/nonexistent/helper"
        self.assertEqual(self.r.start(), 1)
        self.assertIsNone(self.r.read_pid())
        self.assertIn("cannot start", self.status()["error"])

    def test_it_stops_by_itself_after_the_maximum_time(self):
        self.source(WALK)
        self.assertEqual(self.r.start(max_hours=1.5 / 3600), 0)
        self.assertTrue(self.wait(lambda: self.r.read_pid() is None, 8))
        self.assertFalse(self.status()["running"])

    def test_the_helper_command_and_options(self):
        os.environ.pop("GOTHI_GPS_CMD", None)
        self.assertEqual(self.r.source_cmd(False), ["python2.5", "/opt/gothi/modules/gps/gps-stream.py", "--raw"])
        self.assertEqual(self.r.source_cmd(True)[-1], "--assisted")

    def test_stale_pid_file_and_usage(self):
        os.makedirs(self.r.STATE_DIR, exist_ok=True)
        with open(self.r.PIDFILE, "w") as f:
            f.write("999999")
        self.assertIsNone(self.r.read_pid())
        self.assertFalse(os.path.exists(self.r.PIDFILE))
        self.assertEqual(self.r.main(["recorder.py"]), 2)
        self.assertEqual(self.r.stop(), 0)


if __name__ == "__main__":
    unittest.main()
