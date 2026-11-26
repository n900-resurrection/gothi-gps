TEST_NAME=gothi-gps
need_pkg gothi-gps
ok manifest test -f /opt/gothi/modules/gps/module.json
ok helper-is-executable test -x /opt/gothi/modules/gps/gps-stream.py
ok helper-compiles python2.5 -c "compile(open('/opt/gothi/modules/gps/gps-stream.py').read(), 'gps-stream.py', 'exec')"
contains module-found "GPS (monitor)" sh -c 'PYTHONPATH=/opt/gothi/lib python3 -W ignore -m gothi --modules'
contains no-failures "0 failed" sh -c 'PYTHONPATH=/opt/gothi/lib python3 -W ignore -m gothi --modules'
# run the helper for a few seconds as the user, like gothi does: it prints blocks and puts the system switch of the GPS back
KEY=/system/nokia/location/gps-disabled
before=$(su user -c "gconftool-2 -g $KEY")
run_helper() { su user -c "DISPLAY=:0 timeout -t 8 python2.5 /opt/gothi/modules/gps/gps-stream.py 2>&1"; }
contains helper-prints-state "Fix:" run_helper
contains helper-starts "Starting GPS" run_helper
t_switch_restored() { [ "$(su user -c "gconftool-2 -g $KEY")" = "$before" ] && echo restored; }
contains gps-switch-restored "restored" t_switch_restored
summary
