# Tach multiplex theo byte1 / byte5, tuong quan lai voi dRel/vRel. Doc npz da luu.
import numpy as np, collections
OUT="/data/backup_radar"
def fields(B):
  le=sum(B[:,i].astype(np.uint64)<<np.uint64(8*i) for i in range(8))
  be=sum(B[:,i].astype(np.uint64)<<np.uint64(8*(7-i)) for i in range(8))
  for en,U in (('LE',le),('BE',be)):
    for L in (8,10,11,12,13,16):
      for st in range(0,65-L):
        x=((U>>np.uint64(st))&np.uint64((1<<L)-1)).astype(float)
        yield en,st,L,x
for a in (0x313,0x314,0x315,0x326,0x327,0x329,0x30C,0x324):
  z=np.load(f"{OUT}/corr_{a:03X}.npz"); B,M=z['B'],z['M']; ok=M[:,2]>0
  for mb in (1,5):
    vals=collections.Counter(B[:,mb]); 
    if len(vals)>6: continue
    print(f"\n0x{a:03X} mux byte{mb}: gia tri {dict(sorted((hex(k),v) for k,v in vals.items()))}")
    for mv in sorted(vals):
      sel=ok&(B[:,mb]==mv); d,v=M[sel,0],M[sel,1]
      if sel.sum()<200: continue
      best=[]
      for en,st,L,x in fields(B[sel]):
        if x.std()==0: continue
        for sg in (0,1):
          xx=np.where(x>=2**(L-1),x-2**L,x) if sg else x
          if xx.std()==0: continue
          rd=np.corrcoef(xx,d)[0,1]; rv=np.corrcoef(xx,v)[0,1]
          best.append((max(abs(rd),abs(rv)),rd,rv,en,st,L,sg,xx))
      best.sort(key=lambda r:r[0],reverse=True)
      for r in best[:2]:
        k,b=np.polyfit(r[7],d if abs(r[1])>=abs(r[2]) else v,1)
        print(f"   mux={mv:#04x} n={sel.sum():5d} {r[3]} bit{r[4]:2d} dai{r[5]:2d} {'s' if r[6] else 'u'} r_dRel={r[1]:+.3f} r_vRel={r[2]:+.3f}  y~{k:+.4f}*x{b:+.2f}")
