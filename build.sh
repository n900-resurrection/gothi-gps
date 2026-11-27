#!/bin/bash
# Nothing to compile: the module is a folder with a manifest. Check that the manifest is valid JSON and copy it to build/out.
#   make -C apps/gothi-gps build
# Output: /project/build/out/gothi-gps-$VERSION/module/
set -euo pipefail
VERSION="${VERSION:-0.3.0}"
PROJ=/project
HERE="$PROJ/apps/gothi-gps"
OUT="$PROJ/build/out/gothi-gps-$VERSION"
python3 -I -c 'import json,sys; d = json.load(open(sys.argv[1])); assert d["type"] == "monitor" and d["run"]; print("manifest ok:", d["title"])' "$HERE/module/module.json"
rm -rf "$OUT"; mkdir -p "$OUT"
cp -r "$HERE/module" "$OUT/module"
python3 -I -c 'import json,sys; d = json.load(open(sys.argv[1])); assert d["type"] == "monitor" and "--assisted" in d["run"]; print("manifest ok:", d["title"])' "$HERE/module-assisted/module.json"
cp -r "$HERE/module-assisted" "$OUT/module-assisted"
python3 -I -c 'import json,sys; d = json.load(open(sys.argv[1])); assert d["type"] == "python" and d["entry"] == "module.py"; print("manifest ok:", d["title"])' "$HERE/module-track/module.json"
python3 -I -m py_compile "$HERE"/module-track/*.py && rm -rf "$HERE"/module-track/__pycache__     # the track recorder and its screens are Python 3: the syntax is checked here
cp -r "$HERE/module-track" "$OUT/module-track"
grep -q "^#!/usr/bin/python2.5" "$HERE/module/gps-stream.py"   # the helper is Python 2.5: its syntax is checked on the phone by test.sh
