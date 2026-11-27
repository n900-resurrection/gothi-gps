#!/bin/bash
# Package the module as a .deb for Maemo 5: make -C apps/gothi-gps deb
# Output: /project/build/deb/gothi-gps_<VERSION>-<REV>_armel.deb
set -euo pipefail
PROJ=/project
. "$PROJ/scripts/debpack.sh"

PKG=gothi-gps
VERSION="${VERSION:-0.3.0}"
OUT="$PROJ/build/out/gothi-gps-$VERSION"
STAGE="$PROJ/build/deb/stage-$PKG"
HERE="$PROJ/apps/gothi-gps"
[ -f "$OUT/module/module.json" ] || { echo "Missing build output in $OUT, run build.sh first (make build)"; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE/opt/gothi/modules"
cp -r "$OUT/module" "$STAGE/opt/gothi/modules/gps"
chmod 755 "$STAGE/opt/gothi/modules/gps/gps-stream.py"
cp -r "$OUT/module-assisted" "$STAGE/opt/gothi/modules/gps-assisted"        # the same helper with --assisted (A-GPS)
cp -r "$OUT/module-track" "$STAGE/opt/gothi/modules/gps-track"              # the track recorder (GPX export); uses the helper above with --raw
chmod 755 "$STAGE/opt/gothi/modules/gps-track/recorder.py"

SECTION=user/utilities
DEPENDS="gothi (>= 0.11.0), python-location, python3.11"
DISPLAY_NAME="gothi: GPS"
SHORT_DESC="Modules for gothi: GPS data, A-GPS and a track recorder with GPX export"
LONG_DESC="Adds the entry GPS to the menu Modules of gothi (restart gothi after the installation): the screen shows whether the GPS has a fix, the satellites in view and in use and, with a fix, the position, altitude, speed and track. The GPS is switched on while the page is open and off when you leave it.
The entry GPS track records where you went (in the background, also when gothi is closed or the screen is off) into ~/MyDocs/gothi/tracks and exports the track as a GPX file; it lists the tracks with statistics.
It needs a view of the sky (it does not work in a flat). The GPS is started with the satellite method only, nothing is sent to a server. The system switch of the GPS (Settings, Location) is turned on for the time of the run and put back afterwards.
Upstream: https://github.com/n900-resurrection/nokia-n900-apps"
debpack_build
