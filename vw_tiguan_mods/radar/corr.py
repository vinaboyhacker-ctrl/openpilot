# Buoc 2: tuong quan bit-field tren bus 2 voi leadOne.dRel / vRel. Chi doc log.
# Dung: corr.py <route> <doan,doan,...>   -> in bang tom tat, luu npz
import sys, re, numpy as np, collections
from openpilot.tools.lib.logreader import LogReader
R, segs = sys.argv[1], sys.argv[2].split(',')
OUT="/data/backup_radar"
DBC=open("/data/openpilot/opendbc_repo/opendbc/dbc/vw_mqb.dbc").read()
names={int(m.group(1)):m.group(2) for m in re.finditer(r"^BO_ (\d+) (\w+):", DBC, re.M)}
CAND={0x181,0x29C,0x2AC,0x313,0x314,0x315,0x322,0x326,0x327,0x328,0x329,0x460,0x48A,0x30C,0x324,0x117,0x2A7,0x2A9,0x2B7,0x30F}
data=collections.defaultdict(list)   # id -> list of (u8 bytes)
meta=collections.defaultdict(list)   # id -> list of (dRel,vRel,ok,longActive,vEgo,t)
lead=(0.,0.,False); la=False; ve=0.; prob=0.
for s in segs:
  try:
    for m in LogReader(f"{OUT}/logs/{R}--{s}/rlog.zst"):
      w=m.which()
      if w=='radarState':
        l=m.radarState.leadOne; lead=(l.dRel,l.vRel,bool(l.status) and l.modelProb>0.9)
      elif w=='carControl': la=m.carControl.longActive
      elif w=='carState': ve=m.carState.vEgo
      elif w=='can':
        t=m.logMonoTime*1e-9
        for c in m.can:
          if c.src==2 and c.address in CAND and len(c.dat)==8:
            data[c.address].append(np.frombuffer(c.dat,np.uint8))
            meta[c.address].append((lead[0],lead[1],lead[2] and ve>3,la,ve,t))
  except Exception as e: print("doan",s,"loi",e)
res=[]; info=[]
for a in sorted(data):
  B=np.array(data[a]); M=np.array(meta[a],dtype=float); ok=M[:,2]>0
  np.savez_compressed(f"{OUT}/corr_{a:03X}.npz",B=B,M=M)
  if ok.sum()<200: continue
  le=B.astype(np.uint64); le=sum(le[:,i]<<np.uint64(8*i) for i in range(8))
  be=B.astype(np.uint64); be=sum(be[:,i]<<np.uint64(8*(7-i)) for i in range(8))
  d,v=M[ok,0],M[ok,1]
  nuniq=[len(np.unique(B[:,i])) for i in range(8)]
  info.append((a,nuniq))
  for endian,U in (('LE',le),('BE',be)):
    for L in (8,10,12,16):
      for st in range(0,65-L):
        x=((U[ok]>>np.uint64(st))&np.uint64((1<<L)-1)).astype(float)
        if x.std()==0: continue
        for sg in (0,1):
          xx=np.where(x>=2**(L-1),x-2**L,x) if sg else x
          if xx.std()==0: continue
          rd=np.corrcoef(xx,d)[0,1]; rv=np.corrcoef(xx,v)[0,1]
          # he so tuyen tinh: dRel ~ k*x+b
          kd=np.polyfit(xx,d,1)[0] if abs(rd)>0.5 else 0
          res.append((abs(rd),rd,rv,a,endian,st,L,sg,kd,len(xx)))
def show(key,title,idx):
  print(f"\n== TOP 10 theo |r| voi {title}")
  print("ID     ten           endian bit  dai dau  r_dRel  r_vRel  he_so  n")
  best={}
  for r in sorted(res,key=key,reverse=True):
    k=(r[3],r[4],r[5]//4)          # gop cac bit sat nhau
    if k in best: continue
    best[k]=1
    print(f"0x{r[3]:03X} {names.get(r[3],'LA'):<13} {r[4]}  {r[5]:3d} {r[6]:3d}  {'s' if r[7] else 'u'}  {r[1]:+.3f}  {r[2]:+.3f}  {r[8]:+.3f} {r[9]}")
    if len(best)>=10: break
show(lambda r:abs(r[1]),"dRel",1); show(lambda r:abs(r[2]),"vRel",2)
print("\n== So gia tri khac nhau moi byte (phat hien bo dem/checksum/multiplex):")
for a,n in info: print(f"0x{a:03X} {names.get(a,'LA'):<13}", n)
