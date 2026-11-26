#!/usr/bin/python2.5
# gps-stream: prints the state of the GPS of the N900 as blocks of lines (every block ends with an empty line) until it gets SIGTERM.
# Runs with the Python 2.5 of Maemo, because only that one has the module `location` (liblocation). Written for gothi (module gps).
#   - the GPS is switched on with the method GNSS only (no network help: nothing leaves the phone)
#   - the system switch /system/nokia/location/gps-disabled is set to false for the time of the run and put back at the end
#   - the position is shown only with a fix (the "last known" position of the system is not shown as if it were live)
import os
import signal
import subprocess
import sys
import time

import gobject
import location

KEY = "/system/nokia/location/gps-disabled"
MODES = {0: "unknown", 1: "none", 2: "2D", 3: "3D"}
ERRORS = {0: "rejected dialog", 1: "rejected settings", 2: "no Bluetooth GPS", 3: "not allowed offline", 4: "system"}


def gconf(*args):
    try:
        p = subprocess.Popen(["gconftool-2"] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.communicate()[0].strip()
    except OSError:
        return ""


def known(x):
    return x == x and x is not None            # not NaN


def out(lines):
    sys.stdout.write("\n".join(lines) + "\n\n")
    sys.stdout.flush()


was = gconf("-g", KEY)
if was == "true":
    gconf("-s", "-t", "bool", KEY, "false")

control = location.GPSDControl.get_default()
device = location.GPSDevice()
loop = gobject.MainLoop()
state = {"error": None, "since": time.time()}


def on_error(ctl, *args):
    state["error"] = args[0] if args else -1


def frame():
    if state["error"] is not None:
        return ["GPS error: %s" % ERRORS.get(state["error"], state["error"])]
    f = device.fix
    mode = f[0]
    lines = ["Fix: %s" % MODES.get(mode, mode), "Satellites: %s view, %s used" % (device.satellites_in_view, device.satellites_in_use)]
    if mode >= 2:
        lines.append("Lat %.5f" % f[4])
        lines.append("Lon %.5f" % f[5])
        if mode == 3 and known(f[7]):
            lines.append("Alt %.0f m" % f[7])
        if known(f[11]):
            lines.append("Speed %.1f km/h" % f[11])
        if known(f[9]):
            lines.append("Track %.0f deg" % f[9])
        if known(f[6]):
            lines.append("Error +-%.0f m" % (f[6] / 100.0))
        if known(f[2]):
            lines.append(time.strftime("UTC %H:%M:%S", time.gmtime(f[2])))
    elif device.satellites_in_view == 0 and time.time() - state["since"] > 30:
        lines.append("No satellite seen:")
        lines.append("go outside or to a window")
    return lines


def tick():
    out(frame())
    return True


def finish(*args):
    loop.quit()


control.connect("error", on_error)
signal.signal(signal.SIGTERM, finish)
signal.signal(signal.SIGINT, finish)
control.set_properties(preferred_method=location.METHOD_GNSS, preferred_interval=location.INTERVAL_1S)
out(["Starting GPS..."])
try:
    control.start()
    gobject.timeout_add(500, tick)             # also lets the signal handlers run
    loop.run()
finally:
    try:
        control.stop()
    finally:
        if was == "true":
            gconf("-s", "-t", "bool", KEY, "true")
