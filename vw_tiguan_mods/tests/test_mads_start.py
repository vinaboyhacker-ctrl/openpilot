# Mo phong _sp_auto_lkas_on_start (doi tuong gia). Dung: test_mads_start.py <mads.py>
import sys, importlib.util, types
from cereal import car
spec=importlib.util.spec_from_file_location("mads_t", sys.argv[1]); M=importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
G=car.CarState.GearShifter
class Ev:
  def __init__(s): s.l=[]
  def add(s,e): s.l.append(e)
class SM:
  def __init__(s): s.noentry=False
  def check_contains(s,t): return s.noentry
def mk():
  o=M.ModularAssistiveDrivingSystem.__new__(M.ModularAssistiveDrivingSystem)
  o._sp_auto_lkas_pending=True; o.main_enabled_toggle=True; o.enabled=False
  o.selfdrive=types.SimpleNamespace(initialized=False); o.events_sp=Ev(); o.state_machine=SM(); return o
def cs(avail=True,gear=G.drive,brake=False):
  c=car.CarState.new_message(brakePressed=brake,gearShifter=gear); c.cruiseState.available=avail; return c
ok=True
def chk(n,cond):
  global ok; ok&=cond; print(("OK  " if cond else "SAI ")+n)
o=mk(); o._sp_auto_lkas_on_start(cs()); chk("dang khoi dong -> chua bat, giu co", not o.events_sp.l and o._sp_auto_lkas_pending)
o.selfdrive.initialized=True; o._sp_auto_lkas_on_start(cs(gear=G.park)); chk("san sang nhung so P -> cho", not o.events_sp.l and o._sp_auto_lkas_pending)
o._sp_auto_lkas_on_start(cs(brake=True)); chk("so D nhung dap phanh -> cho", not o.events_sp.l)
o.state_machine.noentry=True; o._sp_auto_lkas_on_start(cs()); chk("co NO_ENTRY -> cho", not o.events_sp.l); o.state_machine.noentry=False
o._sp_auto_lkas_on_start(cs()); chk("so D, nha phanh -> GUI lkasEnable", len(o.events_sp.l)==1 and not o._sp_auto_lkas_pending)
o._sp_auto_lkas_on_start(cs()); chk("lan sau -> KHONG gui nua (chi 1 lan)", len(o.events_sp.l)==1)
o=mk(); o.selfdrive.initialized=True; o._sp_auto_lkas_on_start(cs(avail=False)); chk("ACC main tat -> huy, khong gui", not o.events_sp.l and not o._sp_auto_lkas_pending)
o=mk(); o.enabled=True; o.selfdrive.initialized=True; o._sp_auto_lkas_on_start(cs()); chk("da bat san -> khong gui", not o.events_sp.l and not o._sp_auto_lkas_pending)
o=mk(); o.main_enabled_toggle=False; o.selfdrive.initialized=True; o._sp_auto_lkas_on_start(cs()); chk("tat MadsMainCruiseAllowed -> khong gui", not o.events_sp.l)
print("KET QUA:", "TAT CA OK" if ok else "CO LOI")
