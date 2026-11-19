#!/bin/sh
# Phan tich chuyen moi nhat (hoac $1). CHI DOC LOG, khong gui gi vao xe.
# Dung: sh /data/backup_radar/run_all.sh [route]   (chay khi xe TAT MAY)
set -e
[ "$(cat /data/params/d/IsOnroad)" = "1" ] && { echo "Xe dang chay - dung lai"; exit 1; }
cd /data/media/0/realdata
R=${1:-$(ls -d *--*--* | sed 's/--[0-9]*$//' | sort -u | tail -1)}
B=/data/backup_radar; mkdir -p $B/logs
for d in $R--*; do mkdir -p $B/logs/$d; for f in rlog.zst qlog.zst; do [ -f $d/$f ] && ln -f $d/$f $B/logs/$d/$f; done; done
cd /data/openpilot; export PYTHONPATH=/data/openpilot; PY="nice -n 10 /usr/local/venv/bin/python3"
$PY $B/pick_segs.py $R 2>/dev/null > $B/segs_$R.txt
S=$(sort -k2 -n -r $B/segs_$R.txt | awk '$2>=60{print $1}' | head -14 | paste -sd,)
echo "Route $R, doan dung: $S"
$PY $B/bus_survey.py $B/logs/$R--$(echo $S | cut -d, -f1)/rlog.zst 2>/dev/null > $B/bus_survey_$R.txt
$PY $B/corr.py $R $S 2>/dev/null > $B/corr_$R.txt
$PY $B/demux.py 2>/dev/null > $B/demux_$R.txt
$PY $B/consist.py 2>/dev/null > $B/consist_$R.txt
echo "Xong. Ket qua: $B/*_$R.txt"
