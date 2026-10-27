#!/bin/bash
# Run as root on the comma (adb shell). Swaps the pre-built /data/carrot_new into /data/openpilot,
# keeps stock sunnypilot in /data/openpilot_sp, then re-runs scons for the new path in the background.
set -e
[ -d /data/carrot_new ] || { echo "NO /data/carrot_new"; exit 1; }
[ -e /data/openpilot_sp ] && { echo "/data/openpilot_sp already exists, aborting"; exit 1; }
mv /data/openpilot /data/openpilot_sp
mv /data/carrot_new /data/openpilot
chown -R comma:comma /data/openpilot
mkdir -p /data/tmp
cat > /data/tmp/carrot_finish.sh <<'EOS'
#!/bin/bash
export PATH=/usr/local/venv/bin:$PATH
cd /data/openpilot || exit 1
git log --oneline -1
source ./launch_env.sh
export PYTHONPATH=/data/openpilot
echo "== BUILD =="
scons -j8 > /data/tmp/carrot_build.log 2>&1
code=$?
tail -20 /data/tmp/carrot_build.log
echo "BUILD_EXIT=$code"
EOS
chmod 755 /data/tmp/carrot_finish.sh
nohup setsid sudo -u comma -H bash /data/tmp/carrot_finish.sh > /data/tmp/carrot_run.log 2>&1 < /dev/null &
echo "SWAPPED. Building in background. Check with: tail -3 /data/tmp/carrot_run.log"
echo "When it shows BUILD_EXIT=0, run: reboot"
