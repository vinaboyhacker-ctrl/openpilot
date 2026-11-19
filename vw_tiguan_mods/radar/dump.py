import numpy as np, sys
OUT="/data/backup_radar"
t0s=None
Z={a:np.load(f"{OUT}/corr_{a:03X}.npz") for a in (0x313,0x314,0x315)}
# moc thoi gian: doan 58 la doan cuoi trong danh sach -> lay khoang cuoi
tend=max(Z[0x313]['M'][:,5]); a0,a1=tend-60+float(sys.argv[1]),tend-60+float(sys.argv[2])
for a,z in Z.items():
  B,M=z['B'],z['M']; sel=np.where((M[:,5]>=a0)&(M[:,5]<=a1))[0][::int(sys.argv[3])]
  print(f"== 0x{a:03X}")
  for i in sel: print(f" t={M[i,5]-tend+60:5.1f} d={M[i,0]:5.1f} vR={M[i,1]*3.6:6.1f} v={M[i,4]*3.6:4.0f}  "+" ".join(f"{b:02X}" for b in B[i]))
