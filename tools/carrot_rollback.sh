#!/bin/bash
# Run as root on the comma. Puts stock sunnypilot back and keeps carrot in /data/carrot_new.
set -e
[ -d /data/openpilot_sp ] || { echo "NO /data/openpilot_sp"; exit 1; }
[ -e /data/carrot_new ] && { echo "/data/carrot_new already exists, aborting"; exit 1; }
mv /data/openpilot /data/carrot_new
mv /data/openpilot_sp /data/openpilot
echo "ROLLED BACK. Run: reboot"
