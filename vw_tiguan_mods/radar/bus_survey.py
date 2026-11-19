# Thong ke ID CAN theo bus tu 1 rlog. Chi doc.
import sys, re, collections
from openpilot.tools.lib.logreader import LogReader
DBC="/data/openpilot/opendbc_repo/opendbc/dbc/vw_mqb.dbc"
names={int(m.group(1)):m.group(2) for m in re.finditer(r"^BO_ (\d+) (\w+):", open(DBC).read(), re.M)}
cnt=collections.Counter(); dlc=collections.defaultdict(set); send=collections.Counter(); t0=t1=None
for m in LogReader(sys.argv[1]):
  w=m.which()
  if w not in ('can','sendcan'): continue
  t=m.logMonoTime*1e-9; t0=t0 or t; t1=t
  for c in getattr(m,w):
    if w=='can':
      if c.src>=128: continue
      cnt[(c.src,c.address)]+=1; dlc[(c.src,c.address)].add(len(c.dat))
    else: send[(c.src,c.address)]+=1
dur=t1-t0
buses=sorted({b for b,_ in cnt})
print(f"Thoi luong {dur:.0f}s")
for b in buses:
  ids=sorted(a for bb,a in cnt if bb==b)
  unk=[a for a in ids if a not in names]
  print(f"\n== BUS {b}: {len(ids)} ID, {len(ids)-len(unk)} co trong DBC, {len(unk)} LA")
  rows=[a for a in ids if a not in names or re.search(r"ACC|AWV|ANB|Radar|LDW|SWA|RCTA|Objekt|Abstand|Ziel|EML|HCA|TSK|GRA|Kamera|KLR|PLA",names.get(a,""))]
  for a in rows:
    k=(b,a); print(f"  0x{a:03X} {names.get(a,'??LA??'):<16} {cnt[k]/dur:6.1f}Hz dlc={sorted(dlc[k])}  {'bus0+2' if (0,a) in cnt and (2,a) in cnt else ''}")
print("\n== comma GUI (sendcan):", ", ".join(f"b{b}:0x{a:03X}({names.get(a,'?')})" for (b,a) in sorted(send)))
only2=sorted(a for b,a in cnt if b==2 and (0,a) not in cnt); only0=sorted(a for b,a in cnt if b==0 and (2,a) not in cnt)
print("Chi co o bus2 (bi chan/khong chuyen):", ", ".join(f"0x{a:03X}{'('+names[a]+')' if a in names else ''}" for a in only2))
print("Chi co o bus0:", ", ".join(f"0x{a:03X}{'('+names[a]+')' if a in names else ''}" for a in only0))
