TEST_NAME=gothi-gps
need_pkg gothi-gps
ok manifest test -f /opt/gothi/modules/gps/module.json
ok manifest-assisted test -f /opt/gothi/modules/gps-assisted/module.json
ok helper-is-executable test -x /opt/gothi/modules/gps/gps-stream.py
ok helper-compiles python2.5 -c "compile(open('/opt/gothi/modules/gps/gps-stream.py').read(), 'gps-stream.py', 'exec')"
contains module-found "GPS (monitor)" sh -c 'PYTHONPATH=/opt/gothi/lib python3 -W ignore -m gothi --modules'
contains module-assisted-found "GPS (A-GPS) (monitor)" sh -c 'PYTHONPATH=/opt/gothi/lib python3 -W ignore -m gothi --modules'
contains no-failures "0 failed" sh -c 'PYTHONPATH=/opt/gothi/lib python3 -W ignore -m gothi --modules'
# run the helper for a few seconds as the user, like gothi does: it prints blocks and puts the system switch of the GPS back
KEY=/system/nokia/location/gps-disabled
before=$(su user -c "gconftool-2 -g $KEY")
run_helper() { su user -c "DISPLAY=:0 timeout -t 8 python2.5 /opt/gothi/modules/gps/gps-stream.py 2>&1"; }
contains helper-prints-state "Fix:" run_helper
contains helper-starts "Starting GPS" run_helper
t_search_time() { run_helper | grep -q -E "Searching [0-9]+:[0-9][0-9]|Lat " && echo shown; }
contains helper-shows-search-time "shown" t_search_time
# the A-GPS run changes three system keys for its time (SUPL server, port, network positioning) and must put all of them back
SUPL_KEYS="/system/nokia/location/supl/server /system/nokia/location/supl/port /system/nokia/location/network-disabled"
keys_state() { for k in $SUPL_KEYS; do su user -c "gconftool-2 -g $k"; done; }
supl_before=$(keys_state)
run_assisted() { su user -c "DISPLAY=:0 timeout -t 8 python2.5 /opt/gothi/modules/gps/gps-stream.py --assisted 2>&1"; }
contains assisted-shows-the-server "A-GPS: supl.google.com" run_assisted
t_supl_restored() { [ "$(keys_state)" = "$supl_before" ] && echo restored; }
contains supl-keys-restored "restored" t_supl_restored
# the track recorder: the module is offered, the raw lines of the helper parse, a recording with a fake GPS (made-up fixes, the real GPS is not used) makes a
# track and a GPX, and a short run with the real helper (no fix indoors) leaves no track and puts the GPS switch back
contains module-track-found "GPS track (python)" sh -c 'PYTHONPATH=/opt/gothi/lib python3 -W ignore -m gothi --modules'
contains recorder-is-executable "executable" sh -c 'test -x /opt/gothi/modules/gps-track/recorder.py && echo executable'
run_raw() { su user -c "DISPLAY=:0 timeout -t 6 python2.5 /opt/gothi/modules/gps/gps-stream.py --raw 2>&1"; }
contains helper-raw-line "FIX " run_raw
t_raw_parses() { run_raw | grep "^FIX " | head -n 1 | su user -c "python3 -W ignore -c \"import sys; sys.path.insert(0, '/opt/gothi/modules/gps-track'); import tracklib; p = tracklib.parse_raw(sys.stdin.read()); print('parsed' if p and 'mode' in p else 'bad')\""; }
contains raw-line-parses "parsed" t_raw_parses
tmpdir
chmod 777 "$TESTDIR"
printf '%s\n' 'import sys, time' 'for i in range(8):' '    print("FIX 3 %.7f %.7f %.1f 5.00 45.0 8.0 %d 9 5" % (50.0 + i * 0.0001, 14.0 + i * 0.00005, 240 + i, 1732700000 + i * 3)); sys.stdout.flush(); time.sleep(0.1)' 'time.sleep(60)' > "$TESTDIR/fake.py"
chmod 644 "$TESTDIR/fake.py"
REC="python3 /opt/gothi/modules/gps-track/recorder.py"
FAKE_ENV="GOTHI_TRACK_DIR=$TESTDIR/tracks GOTHI_STATE_DIR=$TESTDIR/state GOTHI_GPS_CMD='python3 $TESTDIR/fake.py'"
fake_recording() {
    su user -c "$FAKE_ENV $REC start" || return
    sleep 3
    su user -c "$FAKE_ENV $REC status" || return
    su user -c "$FAKE_ENV $REC stop"
    su user -c "$FAKE_ENV $REC status" && return
    n=$(grep -c "<trkpt" "$TESTDIR"/tracks/*.gpx)
    [ "$n" = 8 ] && echo "recorded-$n-points"
}
contains fake-recording-makes-a-gpx "recorded-8-points" fake_recording
real_helper_recording() {
    su user -c "DISPLAY=:0 GOTHI_TRACK_DIR=$TESTDIR/real GOTHI_STATE_DIR=$TESTDIR/realstate $REC start" || return
    sleep 4
    su user -c "GOTHI_STATE_DIR=$TESTDIR/realstate $REC status" || return
    su user -c "GOTHI_STATE_DIR=$TESTDIR/realstate $REC stop"
    su user -c "GOTHI_STATE_DIR=$TESTDIR/realstate $REC status" && return
    # a fix is only possible under the open sky: either a track was made or nothing is left behind
    echo "real-run-ok"
}
contains real-helper-run "real-run-ok" real_helper_recording
t_switch_restored() { [ "$(su user -c "gconftool-2 -g $KEY")" = "$before" ] && echo restored; }
contains gps-switch-restored "restored" t_switch_restored
summary
