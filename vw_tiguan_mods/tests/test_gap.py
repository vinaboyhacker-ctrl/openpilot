# Mo phong vong kin MPC doc (solver that), so sanh khoang cach. Khong gui gi vao xe.
import sys, importlib.util, types, numpy as np
from cereal import log
P=log.LongitudinalPersonality
def load(path,name):
  spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
def lead(st,d,v):
  return types.SimpleNamespace(status=st,dRel=d,vLead=v,aLeadK=0.0,aLeadTau=1.5,modelProb=1.0)
def sim(M,pers,v0,vl,d0,secs=60):
  mpc=M.LongitudinalMpc(); v=v0; a=0.0; x=0.0; xl=d0; dt=0.05
  for _ in range(int(secs/dt)):
    rs=types.SimpleNamespace(leadOne=lead(True,xl-x,vl),leadTwo=lead(False,0,0))
    mpc.set_weights(prev_accel_constraint=True,personality=pers); mpc.set_cur_state(v,a)
    mpc.update(rs,40.0,personality=pers)
    a=float(np.interp(dt,M.T_IDXS,mpc.a_solution)); v=max(0.0,float(np.interp(dt,M.T_IDXS,mpc.v_solution)))
    x+=v*dt; xl+=vl*dt
  return xl-x, v
for tag,path in (("GOC",sys.argv[1]),("SUA",sys.argv[2])):
  M=load(path,"mpc_"+tag)
  r=[]
  for kmh in (60,100):
    g,_=sim(M,P.relaxed,kmh/3.6,kmh/3.6,80); r.append(f"{kmh}km/h:{g:5.1f}m")
  g,v=sim(M,P.relaxed,30/3.6,0.0,40,40); r.append(f"dung:{g:4.1f}m(v={v*3.6:.1f})")
  g2,_=sim(M,P.aggressive,100/3.6,100/3.6,80); r.append(f"aggr100:{g2:5.1f}m")
  print(tag,"relaxed ->"," | ".join(r))
