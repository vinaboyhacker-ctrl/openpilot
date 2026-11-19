# Do truong bit nhat quan qua nhieu track (dRel, vRel). Doc slots.npy + npz goc.
import numpy as np, collections
OUT="/data/backup_radar"
rows=[]
for a in (0x313,0x314,0x315):
  z=np.load(f"{OUT}/corr_{a:03X}.npz"); B,M=z['B'],z['M']
  for h in (0,4):
    act=B[:,h+1]!=0x81
    for i in np.where(act)[0]:
      rows.append((M[i,5],a*256+int(B[i,h+1]&0x7F),*B[i,h:h+4],M[i,0],M[i,1],M[i,2]))
R=np.array(rows,dtype=float); R=R[np.argsort(R[:,0])]
tracks=[]
for k in np.unique(R[:,1]):
  S=R[R[:,1]==k]; cut=np.where(np.diff(S[:,0])>0.5)[0]+1
  for s in np.split(S,cut):
    ok=s[:,8]>0
    if len(s)>=150 and ok.mean()>0.9 and s[ok,6].std()>2: tracks.append(s[ok])
print("track dung de do:",len(tracks))
H=[t[:,2:6].astype(np.uint64) for t in tracks]
res=[]
for en in ('LE','BE'):
  for L in range(6,17):
    for st in range(0,33-L):
      for sg in (0,1):
        rd=[];rv=[]
        for t,h in zip(tracks,H):
          U=sum(h[:,i]<<np.uint64(8*(i if en=='LE' else 3-i)) for i in range(4))
          x=((U>>np.uint64(st))&np.uint64((1<<L)-1)).astype(float)
          if sg: x=np.where(x>=2**(L-1),x-2**L,x)
          if x.std()==0: rd.append(0);rv.append(0);continue
          rd.append(np.corrcoef(x,t[:,6])[0,1]); rv.append(np.corrcoef(x,t[:,7])[0,1])
        rd,rv=np.array(rd),np.array(rv)
        res.append((en,st,L,sg,rd.mean(),np.median(np.abs(rd)),(np.sign(rd)==np.sign(rd.mean())).mean(),rv.mean(),np.median(np.abs(rv)),(np.sign(rv)==np.sign(rv.mean())).mean()))
for nm,i in (("dRel",4),("vRel",7)):
  print(f"\n== TOP 8 nhat quan voi {nm}: endian bit(trong nua 4 byte) dai dau | r_tb | |r| trung vi | % track cung dau")
  seen=set()
  for r in sorted(res,key=lambda r:-abs(r[i])):
    k=(r[0],r[1]//3)
    if k in seen: continue
    seen.add(k); print(f"  {r[0]} bit{r[1]:2d} dai{r[2]:2d} {'s' if r[3] else 'u'} | {r[i]:+.2f} | {r[i+1]:.2f} | {100*r[i+2]:.0f}%")
    if len(seen)>=8: break
