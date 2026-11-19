# Chon doan co xe truoc tu qlog. In: doan | % co lead | % sunnypilot long | % tu lai | v tb
import sys, glob
from openpilot.tools.lib.logreader import LogReader
R=sys.argv[1]
for d in sorted(glob.glob(f"/data/backup_radar/logs/{R}--*"), key=lambda p:int(p.rsplit('--',1)[1])):
  n=lead=sp=man=0; v=0; la=False; ve=0
  try:
    for m in LogReader(d+"/qlog.zst"):
      w=m.which()
      if w=='carControl': la=m.carControl.longActive
      elif w=='carState': ve=m.carState.vEgo
      elif w=='radarState':
        l=m.radarState.leadOne; n+=1; v+=ve
        if l.status and l.modelProb>0.9 and ve>3:
          lead+=1; sp+=la; man+=(not la)
  except Exception as e: continue
  if n: print(f"{d.rsplit('--',1)[1]} {100*lead/n:.0f} {100*sp/n:.0f} {100*man/n:.0f} {3.6*v/n:.0f}")
