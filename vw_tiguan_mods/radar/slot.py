# Phan tich 1 o vat the: tach track lien tuc, so byte voi d, vRel, tuoi track
import numpy as np
OUT="/data/backup_radar"
rows=[]
for a in (0x313,0x314,0x315):
  z=np.load(f"{OUT}/corr_{a:03X}.npz"); B,M=z['B'],z['M']
  for h in (0,4):
    hdr=B[:,h+1]; act=hdr!=0x81
    for i in np.where(act)[0]:
      rows.append((M[i,5],a,(hdr[i]&0x7F),hdr[i]>>7,B[i,h],B[i,h+2],B[i,h+3],M[i,0],M[i,1],M[i,2],M[i,4]))
R=np.array(rows,dtype=float); R=R[np.argsort(R[:,0])]
print("so mau o co vat the:",len(R))
# track = cung (ID,chi so) va lien tuc (khoang < 0.5s)
tracks=[]; 
for key in sorted(set(zip(R[:,1],R[:,2]))):
  S=R[(R[:,1]==key[0])&(R[:,2]==key[1])]
  cut=np.where(np.diff(S[:,0])>0.5)[0]+1
  for seg in np.split(S,cut):
    if len(seg)>=30: tracks.append((key,seg))
print("so track >=30 mau (~2s):",len(tracks))
print("ID   idx  n   dai_s  r(b2,d) r(b2,tuoi) r(b0,d) r(b3,d) r(b2b3_12,d) d_tb  lead_ok%")
for key,S in sorted(tracks,key=lambda k:-len(k[1]))[:15]:
  t=S[:,0]-S[0,0]; ok=S[:,9]>0
  def r(x,y):
    return np.corrcoef(x,y)[0,1] if x.std()>0 and y.std()>0 else 0
  b2=S[:,5]; b0=S[:,4]; b3=S[:,6]; w=(S[:,5]*16+(S[:,6].astype(int)>>4))
  print(f"{int(key[0]):03X} {int(key[1]):#04x} {len(S):4d} {t[-1]:5.1f}  {r(b2[ok],S[ok,7]):+.2f}   {r(b2,t):+.2f}     {r(b0[ok],S[ok,7]):+.2f}  {r(b3[ok],S[ok,7]):+.2f}   {r(w[ok],S[ok,7]):+.2f}    {S[ok,7].mean() if ok.any() else 0:5.1f} {100*ok.mean():3.0f}")
np.save(f"{OUT}/slots.npy",R)
