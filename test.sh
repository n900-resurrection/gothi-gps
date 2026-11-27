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
t_switch_restored() { [ "$(su user -c "gconftool-2 -g $KEY")" = "$before" ] && echo restored; }
contains gps-switch-restored "restored" t_switch_restored
summary
