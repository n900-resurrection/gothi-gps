"""Track recording for the module GPS track: the lines of `gps-stream.py --raw`, the filter that decides which fixes are kept, the track file (one JSON per
line, written as it goes so a dead battery loses nothing), statistics and the export to GPX 1.1. Pure Python 3 over text and files, so it is tested on a
computer with a made-up route. The positions are personal data: they stay on the phone, nothing is sent anywhere."""
import json
import math
import os
import time
from xml.sax.saxutils import escape

APP = "gothi-gps"
MIN_DIST = 5.0               # metres: a fix closer than this to the last kept one is not kept ...
MIN_TIME = 2.0               # ... and not earlier than this many seconds after it
HEARTBEAT = 30.0             # but one fix every 30 s is kept even when standing still, so the track shows that time passed
MAX_ERROR = 100.0            # metres: a fix that says it is less exact is dropped
MAX_SPEED = 120.0            # m/s (430 km/h): a jump that needs more is a glitch of the receiver and is dropped
ASCENT_STEP = 3.0            # metres: the altitude has to change this much before it counts as climbing (the GPS altitude jitters)


def _f(word):
    try:
        x = float(word)
    except ValueError:
        return None
    return None if x != x else x


def parse_raw(line):
    """One line of `gps-stream.py --raw` -> {"err": code} or {mode, lat, lon, alt, speed (km/h), course, eph (m), time (epoch), sv, su}; None for anything else."""
    w = (line or "").split()
    if len(w) == 2 and w[0] == "ERR":
        return {"err": w[1]}
    if len(w) != 11 or w[0] != "FIX":
        return None
    try:
        mode, sv, su = int(w[1]), int(w[9]), int(w[10])
    except ValueError:
        return None
    lat, lon, alt, speed, course, eph, t = (_f(x) for x in w[2:9])
    if mode >= 2 and (lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    return {"mode": mode, "lat": lat, "lon": lon, "alt": alt, "speed": speed, "course": course, "eph": eph, "time": t, "sv": sv, "su": su}


def distance(a, b):
    """The distance in metres between two points with "lat" and "lon" (haversine)."""
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


class Filter:
    """Decides which fixes become points of the track."""

    def __init__(self):
        self.last = None

    def accept(self, fix, now):
        """Keep the fix? `now` is the time of the point (the time of the fix, or the clock of the phone when the fix has none)."""
        if fix is None or fix.get("mode", 0) < 2 or fix.get("lat") is None:
            return False
        if fix.get("eph") is not None and fix["eph"] > MAX_ERROR:
            return False
        if self.last is None:
            self.last = (fix, now)
            return True
        prev, t0 = self.last
        dt = now - t0
        if dt <= 0:
            return False
        d = distance(prev, fix)
        if d / dt > MAX_SPEED:
            return False
        if (d >= MIN_DIST and dt >= MIN_TIME) or dt >= HEARTBEAT:
            self.last = (fix, now)
            return True
        return False


def point(fix, now):
    """The record of a kept fix, as written to the track file."""
    p = {"t": round(now, 1), "lat": round(fix["lat"], 7), "lon": round(fix["lon"], 7), "m": fix["mode"], "sat": fix["su"]}
    for key, name, nd in (("alt", "ele", 1), ("speed", "sp", 2), ("course", "co", 1), ("eph", "eph", 1)):
        if fix.get(key) is not None:
            p[name] = round(fix[key], nd)
    return p


class TrackWriter:
    """Appends to a track file: a header line and then a line per point, each flushed and synced at once (a point comes every few seconds at most)."""

    def __init__(self, path, name="", started=None):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")
        if os.path.getsize(path) == 0:
            self._write({"v": 1, "name": name, "started": started if started is not None else time.time(), "app": APP})

    def _write(self, d):
        self.f.write(json.dumps(d, separators=(",", ":")) + "\n")
        self.f.flush()
        os.fsync(self.f.fileno())

    def add(self, p):
        self._write(p)

    def close(self):
        self.f.close()


def read_track(path):
    """-> (header, [points]); a half-written last line (power lost) is skipped, a file that is not a track gives ({}, [])."""
    header, pts = {}, []
    try:
        with open(path, encoding="utf-8") as f:
            for i, ln in enumerate(f):
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if not isinstance(d, dict):
                    continue
                if i == 0 and "v" in d:
                    header = d
                elif "lat" in d and "lon" in d and "t" in d:
                    pts.append(d)
    except OSError:
        pass
    return header, pts


def stats(pts):
    """{points, distance (m), duration (s), avg (km/h over the whole time), max (km/h), ascent (m), low, high (m or None), start, end (epoch or None)}."""
    s = {"points": len(pts), "distance": 0.0, "duration": 0.0, "avg": 0.0, "max": 0.0, "ascent": 0.0, "low": None, "high": None, "start": None, "end": None}
    if not pts:
        return s
    s["start"], s["end"] = pts[0]["t"], pts[-1]["t"]
    s["duration"] = max(0.0, s["end"] - s["start"])
    base = None
    for a, b in zip(pts, pts[1:]):
        d = distance(a, b)
        s["distance"] += d
        dt = b["t"] - a["t"]
        speed = b["sp"] if "sp" in b else (d / dt * 3.6 if dt > 0 else 0.0)
        s["max"] = max(s["max"], speed if speed <= MAX_SPEED * 3.6 else 0.0)
    for p in pts:
        e = p.get("ele")
        if e is None:
            continue
        s["low"] = e if s["low"] is None else min(s["low"], e)
        s["high"] = e if s["high"] is None else max(s["high"], e)
        if base is None:
            base = e
        elif e - base >= ASCENT_STEP:
            s["ascent"] += e - base
            base = e
        elif base - e >= ASCENT_STEP:
            base = e
    if s["duration"] > 0:
        s["avg"] = s["distance"] / s["duration"] * 3.6
    return s


def _iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def gpx(header, pts):
    """The text of a GPX 1.1 file: one track with one segment. The tags of a point are in the order of the schema (ele, time, fix, sat)."""
    name = escape(header.get("name") or "track")
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<gpx version="1.1" creator="%s" xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">' % escape(APP)]
    out.append("  <metadata><name>%s</name>%s</metadata>" % (name, "<time>%s</time>" % _iso(pts[0]["t"]) if pts else ""))
    out.append("  <trk>")
    out.append("    <name>%s</name>" % name)
    out.append("    <trkseg>")
    for p in pts:
        inner = ""
        if "ele" in p:
            inner += "<ele>%.1f</ele>" % p["ele"]
        inner += "<time>%s</time>" % _iso(p["t"])
        inner += "<fix>%s</fix>" % ("3d" if p.get("m") == 3 else "2d")
        if p.get("sat") is not None:
            inner += "<sat>%d</sat>" % p["sat"]
        out.append('      <trkpt lat="%.7f" lon="%.7f">%s</trkpt>' % (p["lat"], p["lon"], inner))
    out += ["    </trkseg>", "  </trk>", "</gpx>", ""]
    return "\n".join(out)


def export_gpx(path, out=None):
    """Write the GPX next to the track file (or to `out`); returns the path, None for a track without points."""
    header, pts = read_track(path)
    if not pts:
        return None
    out = out or os.path.splitext(path)[0] + ".gpx"
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(gpx(header, pts))
    os.replace(tmp, out)
    return out


def list_tracks(folder):
    """[{path, name, started, size}] of the track files in the folder, the newest first."""
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for n in names:
        if n.endswith(".jsonl"):
            p = os.path.join(folder, n)
            try:
                header = read_track_header(p)
                out.append({"path": p, "name": header.get("name") or n[:-6], "started": header.get("started") or os.path.getmtime(p), "size": os.path.getsize(p)})
            except OSError:
                continue
    out.sort(key=lambda t: -t["started"])
    return out


def read_track_header(path):
    """Only the header (the first line): a list of many tracks must not read all their points."""
    try:
        with open(path, encoding="utf-8") as f:
            d = json.loads(f.readline())
        return d if isinstance(d, dict) and "v" in d else {}
    except (OSError, ValueError):
        return {}


def delete_track(path):
    """Delete a track file and its GPX; returns the number of files removed."""
    n = 0
    for p in (path, os.path.splitext(path)[0] + ".gpx"):
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass
    return n


def fmt_dist(m):
    return f"{m:.0f} m" if m < 1000 else f"{m / 1000:.2f} km"


def fmt_dur(s):
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def track_name(t):
    """The default name of a track started at epoch t (local time)."""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def file_name(t):
    return time.strftime("track-%Y%m%d-%H%M%S", time.localtime(t))


def write_status(path, d):
    """The state of the recorder for the screens, written atomically (a screen may read it at any moment)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, path)


def read_status(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None
