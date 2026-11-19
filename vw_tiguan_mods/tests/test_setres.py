# Mo phong SET/RES tren file cruise.py chi dinh (khong gui gi vao xe). Dung: test_setres.py <duong_dan_cruise.py>
import sys, importlib.util
from cereal import car, custom
spec=importlib.util.spec_from_file_location("cruise_test", sys.argv[1]); C=importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
BT=car.CarState.ButtonEvent.Type
CP=car.CarParams.new_message(pcmCruise=False); CP_SP=custom.CarParamsSP.new_message()
H=C.VCruiseHelper(CP,CP_SP)
st={'en':False,'prev_en':False,'CS_prev':None}
def step(btn=None,pressed=None,v_kph=60,gas=False):
  CS=car.CarState.new_message(vEgo=v_kph/3.6,gasPressed=gas)
  CS.cruiseState.available=True
  if btn is not None:
    e=car.CarState.ButtonEvent.new_message(type=btn,pressed=pressed); CS.buttonEvents=[e]
  H.update_v_cruise(CS, st['en'], True)
  if st['en'] and not st['prev_en']: H.initialize_v_cruise(st['CS_prev'], False, True)
  st['prev_en']=st['en']; st['CS_prev']=CS
def press(btn,sec,v_kph=60,enable_on_release=False,gas=False):
  step(btn,True,v_kph,gas)
  for _ in range(int(sec*100)-1): step(v_kph=v_kph,gas=gas)
  step(btn,False,v_kph,gas)
  if enable_on_release: st['en']=True   # selfdrived engage o chu ky sau khi nha
  for _ in range(20): step(v_kph=v_kph,gas=gas)
ok=True
def chk(name,exp):
  global ok; got=H.v_cruise_kph; r=abs(got-exp)<0.01; ok&=r
  print(f"{'OK ' if r else 'SAI'} {name:<45} -> {got:g} (mong {exp:g})")
for _ in range(5): step()
press(BT.setCruise,0.2,60,enable_on_release=True); chk("SET lan dau o 60 km/h (engage)",60)
press(BT.setCruise,0.2,60); chk("SET ngan khi dang engage",59)
press(BT.setCruise,0.2,60); chk("SET ngan lan nua",58)
press(BT.resumeCruise,0.2,60); chk("RES ngan khi dang engage",59)
press(BT.resumeCruise,0.3,60); chk("RES ngan lan nua",60)
press(BT.setCruise,1.2,60); chk("GIU SET 1.2s (doi che do) -> khong doi",60)
press(BT.resumeCruise,1.2,60); chk("GIU RES 1.2s (doi che do) -> khong doi",60)
press(BT.setCruise,0.7,60); chk("SET 0.7s (vung giua) -> khong doi",60)
press(BT.accelCruise,0.2,60); chk("Nut + ngan (nhu cu)",61)
press(BT.decelCruise,0.2,60); chk("Nut - ngan (nhu cu)",60)
press(BT.setCruise,0.2,80,gas=True); chk("SET ngan khi dap ga o 80 -> >= 80",80)
st['en']=False
for _ in range(5): step(v_kph=50)
press(BT.resumeCruise,0.2,50,enable_on_release=True); chk("RES lan dau (chua engage) -> toc do cu",80)
st['en']=False
for _ in range(5): step(v_kph=50)
press(BT.setCruise,0.2,50,enable_on_release=True); chk("SET lan dau o 50 -> 50",50)
H.v_cruise_kph=H.v_cruise_min
press(BT.setCruise,0.2,50); chk(f"SET o toc do min -> giu min",H.v_cruise_min)
H.v_cruise_kph=145
press(BT.resumeCruise,0.2,140); chk("RES o 145 -> giu 145",145)
print("KET QUA:", "TAT CA OK" if ok else "CO LOI")
