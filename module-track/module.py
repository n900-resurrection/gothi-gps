"""GPS track for gothi: record where you went and export it as GPX. The recorder (recorder.py) runs in the background, so the recording goes on when gothi is
closed and the screen is off; the screens here start and stop it, show how it goes, list the tracks (statistics), export them as GPX and delete them.
Tracks are in ~/MyDocs/gothi/tracks (a .jsonl per track and, after the recording, the .gpx next to it). Nothing is sent anywhere, except when the
recording is started with A-GPS (the server then learns the cell of the phone). The data code is tracklib.py."""
import os
import subprocess
import sys
import threading
import time

from gothi import keys
from gothi.apps import Message
from gothi.ui import Menu, Scene, ScrollView

import recorder
import tracklib

HERE = os.path.dirname(os.path.abspath(__file__))


def _thread(fn):
    threading.Thread(target=fn, daemon=True).start()


def run_recorder(*args):
    """Run the recorder command (start / stop) as a separate process: a fork inside gothi, which has threads and SDL, is not a good idea."""
    try:
        p = subprocess.run([sys.executable or "python3", os.path.join(HERE, "recorder.py")] + list(args), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=20, start_new_session=True)
        return p.returncode
    except (OSError, subprocess.SubprocessError):
        return 1


class Control:
    """What the screens know about the recorder: its state file once a second, and the commands to start and stop it (in a thread: the screen never waits)."""

    def __init__(self, run=run_recorder, spawn=_thread, clock=time.time, status_path=None, pid=None):
        self.run, self.spawn, self.clock = run, spawn, clock
        self.status_path = status_path or recorder.STATUS
        self.pid = pid or recorder.read_pid
        self.st = None
        self.running = False
        self.busy = None                 # "starting" / "stopping" while a command runs
        self.checked = None
        self.refresh(force=True)

    def refresh(self, force=False):
        now = self.clock()
        if not force and self.checked is not None and now - self.checked < 1.0:
            return False
        self.checked = now
        self.running = self.pid() is not None
        self.st = tracklib.read_status(self.status_path)
        return True

    def start(self, assisted=False):
        if self.busy:
            return
        self.busy = "starting"
        self.spawn(lambda: self._cmd(["start"] + (["--assisted"] if assisted else [])))

    def stop(self):
        if self.busy:
            return
        self.busy = "stopping"
        self.spawn(lambda: self._cmd(["stop"]))

    def _cmd(self, args):
        try:
            self.run(*args)
        finally:
            self.busy = None
            self.refresh(force=True)

    def recording_now(self, path):
        return self.running and bool(self.st) and self.st.get("track") == path


class Record(Scene):
    """Start and stop the recording (OK), and how it goes: time, points, distance and the state of the fix."""

    def __init__(self, ctl, assisted=False):
        self.ctl, self.assisted = ctl, assisted
        self.title = "Record (A-GPS)" if assisted else "Record"
        self.asking = False
        self.was_running = ctl.running

    def tick(self, now, gothi):
        self.ctl.refresh()
        if self.was_running and not self.ctl.running and self.ctl.st and self.ctl.st.get("points"):
            gothi.deed("track_recorded")                       # a recording that ended with something in it
        self.was_running = self.ctl.running

    def key(self, k, gothi):
        if k == keys.OK:
            if self.ctl.running or self.ctl.busy == "stopping":
                self.ctl.stop()
            elif self.assisted and not self.asking:
                self.asking = True                              # A-GPS asks a server: say so first
            else:
                self.asking = False
                self.ctl.start(self.assisted)
        elif k in (keys.BACK, keys.LEFT):
            if self.asking:
                self.asking = False
            else:
                gothi.pop()

    def on_tap(self, x, y, gothi):
        self.key(keys.OK, gothi)

    def lines(self):
        ctl, st = self.ctl, self.ctl.st or {}
        if ctl.running:
            mode = st.get("mode", 0)
            fix = {2: "2D fix", 3: "3D fix"}.get(mode)
            r = [f"{tracklib.fmt_dist(st.get('distance', 0.0))}  {st.get('points', 0)} points",
                 (f"{fix}  {st.get('su', 0)}/{st.get('sv', 0)} sat" if fix else f"searching {st.get('su', 0)}/{st.get('sv', 0)} sat")]
            if not fix and self.ctl.clock() - st.get("started", self.ctl.clock()) > 60 and st.get("su", 0) < 3:
                r.append("needs open sky")
            if st.get("error"):
                r.append(st["error"][:21])
            return r
        r = []
        if st.get("points") and not ctl.running:
            r.append(f"last: {tracklib.fmt_dist(st.get('distance', 0.0))}, {st['points']} points")
        elif st.get("error"):
            r.append(st["error"][:21])
        elif st and not st.get("points") and st.get("started"):
            r.append("last: no fix, nothing kept")
        return r + ["OK = start"]

    def draw(self, c, gothi):
        c.text(2, 2, self.title)
        c.hline(0, 9, c.w)
        ctl = self.ctl
        if self.asking:
            for i, ln in enumerate(("A-GPS asks a server", "(it learns your cell).", "OK = start", "Back = no")):
                c.text(4, 16 + i * 10, ln)
            return
        if ctl.busy:
            c.text(3, 14, "...", scale=2)
            c.text(4, 36, ctl.busy)
            return
        st = ctl.st or {}
        if ctl.running:
            c.text(3, 14, "REC", scale=2)
            el = tracklib.fmt_dur(ctl.clock() - st.get("started", ctl.clock()))
            c.text(c.w - 3 - c.text_width(el), 17, el)
        else:
            c.text(3, 14, "STOP", scale=2)
        for i, ln in enumerate(self.lines()):
            if 32 + i * 9 + 6 > c.h:
                break
            c.text(4, 32 + i * 9, ln)


def _label(t, dist):
    name = t["name"]
    if len(name) == 16 and name[4] == "-" and name[10] == " ":
        name = name[5:]                                          # "2026-11-27 16:42" -> "11-27 16:42"
    return f"{name[:14]} {tracklib.fmt_dist(dist)}"


class Tracks(Menu):
    """The recorded tracks, the newest first; OK opens one."""

    def __init__(self, ctl, folder=None):
        self.ctl, self.folder = ctl, folder or recorder.TRACK_DIR
        tracks = tracklib.list_tracks(self.folder)
        items = []
        for t in tracks:
            _, pts = tracklib.read_track(t["path"])
            items.append((_label(t, tracklib.stats(pts)["distance"]), (lambda g, t=t: TrackMenu(ctl, t))))
        super().__init__("Tracks", items or [("none yet", lambda g: Message("GPS track", ["no tracks yet:", "record one first"]))])


class TrackMenu(Menu):
    def __init__(self, ctl, t):
        self.ctl, self.t = ctl, t
        super().__init__(t["name"][:16], [("Statistics", lambda g: Stats(t)), ("Export GPX", lambda g: self.export(g)),
                                                              ("Delete", lambda g: Confirm(ctl, t))])

    def export(self, gothi):
        if self.ctl.recording_now(self.t["path"]):
            return Message("GPS track", ["recording now:", "stop it first"])
        out = tracklib.export_gpx(self.t["path"])
        if out is None:
            return Message("GPS track", ["no points in this", "track"])
        gothi.deed("gpx_exported")
        return Message("Saved GPX", [os.path.basename(out)[:22], "in " + os.path.basename(os.path.dirname(out)) + "/ of", "MyDocs/gothi"])


class Stats(ScrollView):
    title = "Statistics"

    def __init__(self, t):
        super().__init__()
        self.t = t

    def rows(self, gothi):
        header, pts = tracklib.read_track(self.t["path"])
        s = tracklib.stats(pts)
        r = [f"points {s['points']}", f"distance {tracklib.fmt_dist(s['distance'])}", f"time {tracklib.fmt_dur(s['duration'])}"]
        if s["points"] > 1:
            r += [f"average {s['avg']:.1f} km/h", f"top {s['max']:.1f} km/h"]
        if s["low"] is not None:
            r += [f"altitude {s['low']:.0f} to {s['high']:.0f} m", f"climbed {s['ascent']:.0f} m"]
        if s["start"]:
            r.append("start " + time.strftime("%d.%m. %H:%M", time.localtime(s["start"])))
        if os.path.exists(os.path.splitext(self.t["path"])[0] + ".gpx"):
            r.append("GPX file exists")
        return r


class Confirm(Scene):
    title = "Delete track?"

    def __init__(self, ctl, t):
        self.ctl, self.t = ctl, t

    def key(self, k, gothi):
        if k == keys.OK:
            if self.ctl.recording_now(self.t["path"]):
                gothi.pop()
                gothi.push(Message("GPS track", ["recording now:", "stop it first"]))
                return
            tracklib.delete_track(self.t["path"])
            gothi.pop()                                          # the question
            gothi.pop()                                          # the menu of the track
            gothi.pop()                                          # the list, which still shows it: it is opened again
            gothi.push(Tracks(self.ctl))
        elif k in (keys.BACK, keys.LEFT):
            gothi.pop()

    def on_tap(self, x, y, gothi):
        self.key(keys.OK, gothi)

    def draw(self, c, gothi):
        c.text(2, 2, self.title)
        c.hline(0, 9, c.w)
        for i, ln in enumerate((self.t["name"][:21], "and its GPX file", "", "OK = delete", "Back = keep")):
            c.text(4, 16 + i * 9, ln)


def create(module):
    ctl = Control()
    menu = Menu("GPS track", [("Record", lambda g: Record(ctl)), ("Record with A-GPS", lambda g: Record(ctl, assisted=True)), ("Tracks", lambda g: Tracks(ctl))])
    menu.deed_name = module.deed
    return menu
