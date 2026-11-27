#!/usr/bin/env python3
"""The track recorder of the module GPS track:  python3 recorder.py start [--assisted] | stop | status

`start` leaves a process in the background that runs the GPS helper (`gps-stream.py --raw`, Python 2.5), keeps the fixes that tracklib.Filter accepts in a
track file in ~/MyDocs/gothi/tracks and writes its state to ~/.cache/gothi/gps-track.json for the screens. It goes on when gothi is closed or the screen is
off, so the phone can ride in a pocket. `stop` (or SIGTERM) ends it, writes the GPX next to the track file and puts the GPS off. It also stops by itself
after MAX_HOURS. Without a fix nothing is recorded (a track without a point is deleted). Environment, for the tests: GOTHI_TRACK_DIR, GOTHI_STATE_DIR,
GOTHI_GPS_CMD (the command that prints the lines instead of the helper)."""
import os
import select
import shlex
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tracklib  # noqa: E402

HOME = os.path.expanduser("~")
TRACK_DIR = os.environ.get("GOTHI_TRACK_DIR") or os.path.join(HOME, "MyDocs", "gothi", "tracks")
STATE_DIR = os.environ.get("GOTHI_STATE_DIR") or os.path.join(HOME, ".cache", "gothi")
PIDFILE = os.path.join(STATE_DIR, "gps-track.pid")
STATUS = os.path.join(STATE_DIR, "gps-track.json")
HELPER = "/opt/gothi/modules/gps/gps-stream.py"
MARK = b"recorder.py"
MAX_HOURS = 8


def source_cmd(assisted):
    env = os.environ.get("GOTHI_GPS_CMD")
    if env:
        return shlex.split(env)
    return ["python2.5", HELPER, "--raw"] + (["--assisted"] if assisted else [])


def read_pid(path=None):
    """The pid of the running recorder, None when there is none (a stale file is removed)."""
    path = path or PIDFILE
    try:
        with open(path) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            if MARK not in f.read():
                raise OSError("not ours")                   # the pid was reused by another process
        return pid
    except (OSError, ValueError):
        try:
            os.remove(path)
        except OSError:
            pass
        return None


def run(ready, assisted, max_seconds):
    """The body of the background process."""
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    started = time.time()
    path = os.path.join(TRACK_DIR, tracklib.file_name(started) + ".jsonl")
    writer = tracklib.TrackWriter(path, name=tracklib.track_name(started), started=started)
    st = {"running": True, "pid": os.getpid(), "track": path, "started": started, "points": 0, "distance": 0.0, "mode": 0, "sv": 0, "su": 0,
          "lat": None, "lon": None, "alt": None, "speed": None, "updated": started, "error": None, "gpx": None, "assisted": bool(assisted)}
    try:
        src = subprocess.Popen(source_cmd(assisted), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    except OSError as e:
        st.update(running=False, error=f"cannot start the GPS helper: {e}")
        tracklib.write_status(STATUS, st)
        writer.close()
        os.remove(path)
        return
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    tracklib.write_status(STATUS, st)
    os.write(ready, b"1")
    flt, last, buf = tracklib.Filter(), None, b""
    try:
        while not stop and time.time() - started < max_seconds:
            if select.select([src.stdout], [], [], 1.0)[0]:
                chunk = os.read(src.stdout.fileno(), 4096)
                if not chunk:
                    st["error"] = "the GPS helper ended"
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    fix = tracklib.parse_raw(line.decode("ascii", "replace"))
                    if fix is None:
                        continue
                    if "err" in fix:
                        st["error"] = "GPS error " + fix["err"]
                        continue
                    now = time.time()
                    st.update(mode=fix["mode"], sv=fix["sv"], su=fix["su"], error=None)
                    if fix["mode"] >= 2:
                        st.update(lat=fix["lat"], lon=fix["lon"], alt=fix["alt"], speed=fix["speed"])
                    if flt.accept(fix, fix["time"] if fix["time"] else now):
                        p = tracklib.point(fix, fix["time"] if fix["time"] else now)
                        writer.add(p)
                        if last is not None:
                            st["distance"] += tracklib.distance(last, p)
                        last = p
                        st["points"] += 1
            st["updated"] = time.time()
            tracklib.write_status(STATUS, st)
    finally:
        src.terminate()
        try:
            src.wait(3)
        except subprocess.TimeoutExpired:
            src.kill()
        writer.close()
        st["running"] = False
        st["updated"] = time.time()
        if st["points"]:
            st["gpx"] = tracklib.export_gpx(path)
        else:
            os.remove(path)                                  # nothing was recorded (no fix): no empty track is left
            st["track"] = None
        tracklib.write_status(STATUS, st)
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


def start(assisted=False, max_hours=MAX_HOURS):
    if read_pid():
        return 0
    os.makedirs(STATE_DIR, exist_ok=True)
    r, w = os.pipe()
    if os.fork() == 0:
        os.close(r)
        os.setsid()
        for n in (0, 1, 2):
            os.close(n)
        os.open(os.devnull, os.O_RDWR)
        os.dup2(0, 1)
        os.dup2(0, 2)
        try:
            run(w, assisted, max_hours * 3600)
        except BaseException:
            pass
        os._exit(0)
    os.close(w)
    ok = select.select([r], [], [], 6)[0] and os.read(r, 1) == b"1"
    return 0 if ok else 1


def stop():
    pid = read_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(80):
            if read_pid() is None:
                break
            time.sleep(0.1)
    return 0


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "start":
        return start("--assisted" in argv)
    if cmd == "stop":
        return stop()
    if cmd == "status":
        return 0 if read_pid() else 1
    print("usage: recorder.py start [--assisted] | stop | status", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
