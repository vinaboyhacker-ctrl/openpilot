# Mo phong A+B tren log that (chi doc log). Dung: python test_lead_throttle.py <route_prefix> [t0 t1]
import sys, glob, types, importlib.util
spec=importlib.util.spec_from_file_location('lp', sys.argv[1]); lp=importlib.util.module_from_spec(spec); spec.loader.exec_module(lp)
from openpilot.tools.lib.logreader import LogReader
R=sys.argv[2]; T0=float(sys.argv[3]) if len(sys.argv)>3 else 0; T1=float(sys.argv[4]) if len(sys.argv)>4 else 1e9
segs=sorted(glob.glob(R+'*/rlog.zst'), key=lambda p:int(p.split('--')[-1].split('/')[0]))
o=types.SimpleNamespace(dt=0.05, output_a_target=0.0)
f=lp.LongitudinalPlanner._sp_limit_lead_throttle
t0=None; rs=None; v=0; la=False; nA=nB=n=0; last=-1
for p in segs:
  for m in LogReader(p):
    w=m.which(); t=m.logMonoTime*1e-9
    if t0 is None: t0=t
    tt=t-t0
    if w=='radarState': rs=m.radarState
    elif w=='carState': v=m.carState.vEgo
    elif w=='carControl': la=m.carControl.longActive
    elif w=='longitudinalPlan' and rs is not None:
      a=m.longitudinalPlan.aTarget; o.output_a_target=a
      f(o,{'radarState':rs},v); b=o.output_a_target
      if la:
        n+=1
        if b==0.0 and a>0: nB+=1
        elif b<a: nA+=1
      if T0<=tt<=T1 and tt-last>=0.25:
        last=tt; print('%7.2f v=%5.1f aT=%+5.2f -> %+5.2f lead=%d d=%5.1f vR=%+5.1f'%(tt,v*3.6,a,b,rs.leadOne.status,rs.leadOne.dRel,rs.leadOne.vRel))
print('khi longActive: %d mau, A gioi han %.1f%%, B cat ga %.1f%%'%(n,100*nA/max(n,1),100*nB/max(n,1)))
