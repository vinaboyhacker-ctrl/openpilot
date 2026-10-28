"""
Longitudinal planner hook for the CarrotMan navigation bridge.

Turns `carrotManSP.desiredSpeed` into a planner target. The sunnypilot planner already picks the
lowest target among cruise / SCC / SLA, so this only ever slows the car down.
"""
import cereal.messaging as messaging
from cereal import custom
from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.selfdrive.car.cruise import V_CRUISE_UNSET
from openpilot.sunnypilot.carrot.carrot_logic import NO_LIMIT_KPH

EventNameSP = custom.OnroadEventSP.EventName

PARAMS_UPDATE_FRAMES = 60  # ~3 s at 20 Hz
CAMERA_ALERT_SOURCES = ("cam", "section", "bump")
CAMERA_ALERT_ACTIVE = (3, 4, 5)


class CarrotNaviPlanner:
  def __init__(self):
    self.params = Params()
    self.frame = -1
    self.enabled = self.params.get_bool("CarrotNavi")

    self.output_v_target = V_CRUISE_UNSET
    self.output_a_target = 0.
    self.is_active = False
    self.source = "none"
    self.spd_type = -1
    self.spd_limit = 0
    self.spd_dist = 0
    self.sdi_descr = ""

  def _reset(self) -> None:
    self.output_v_target = V_CRUISE_UNSET
    self.is_active = False
    self.source = "none"
    self.spd_type = -1
    self.spd_limit = 0
    self.spd_dist = 0
    self.sdi_descr = ""

  def reset_outputs(self, a_ego: float = 0.) -> None:
    self._reset()
    self.output_a_target = a_ego

  def update(self, sm: messaging.SubMaster, long_enabled: bool, long_override: bool, v_ego: float, a_ego: float,
             events_sp=None) -> None:
    self.frame += 1
    if self.frame % PARAMS_UPDATE_FRAMES == 0:
      self.enabled = self.params.get_bool("CarrotNavi")

    self._reset()
    self.output_a_target = a_ego

    if not self.enabled or 'carrotManSP' not in sm.data or not sm.alive['carrotManSP']:
      return

    cm = sm['carrotManSP']
    if not cm.connected:
      return

    self.spd_type = int(cm.spdType)
    self.spd_limit = int(cm.spdLimit)
    self.spd_dist = int(cm.spdDist)
    self.sdi_descr = str(cm.sdiDescr)
    self.source = str(cm.desiredSource)

    # Information alert while approaching a camera / section / bump, even without long control
    if events_sp is not None and cm.active in CAMERA_ALERT_ACTIVE and self.spd_dist > 0:
      events_sp.add(EventNameSP.carrotNaviCamera)

    desired_kph = float(cm.desiredSpeed)
    if not (0. < desired_kph < NO_LIMIT_KPH) or not long_enabled or long_override:
      return

    self.output_v_target = desired_kph * CV.KPH_TO_MS
    self.is_active = self.output_v_target < v_ego + 0.5 or self.source in CAMERA_ALERT_SOURCES
