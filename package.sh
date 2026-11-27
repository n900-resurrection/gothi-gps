#!/bin/bash
# Package the module as a .deb for Maemo 5: make -C apps/gothi-gps deb
# Output: /project/build/deb/gothi-gps_<VERSION>-<REV>_armel.deb
set -euo pipefail
PROJ=/project
. "$PROJ/scripts/debpack.sh"

PKG=gothi-gps
VERSION="${VERSION:-0.2.0}"
OUT="$PROJ/build/out/gothi-gps-$VERSION"
STAGE="$PROJ/build/deb/stage-$PKG"
HERE="$PROJ/apps/gothi-gps"
[ -f "$OUT/module/module.json" ] || { echo "Missing build output in $OUT, run build.sh first (make build)"; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE/opt/gothi/modules"
cp -r "$OUT/module" "$STAGE/opt/gothi/modules/gps"
chmod 755 "$STAGE/opt/gothi/modules/gps/gps-stream.py"
cp -r "$OUT/module-assisted" "$STAGE/opt/gothi/modules/gps-assisted"        # the same helper with --assisted (A-GPS)

SECTION=user/utilities
DEPENDS="gothi (>= 0.7.0), python-location"
DISPLAY_NAME="gothi: GPS"
SHORT_DESC="Module for gothi: data of the GPS (fix, satellites, position, speed)"
LONG_DESC="Adds the entry GPS to the menu Modules of gothi (restart gothi after the installation): the screen shows whether the GPS has a fix, the satellites in view and in use and, with a fix, the position, altitude, speed and track. The GPS is switched on while the page is open and off when you leave it.
It needs a view of the sky (it does not work in a flat). The GPS is started with the satellite method only, nothing is sent to a server. The system switch of the GPS (Settings, Location) is turned on for the time of the run and put back afterwards.
Upstream: https://github.com/n900-resurrection/nokia-n900-apps"
debpack_build
