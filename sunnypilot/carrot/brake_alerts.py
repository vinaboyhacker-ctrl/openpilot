"""
Brake sounds:
  chime   - sunnypilot is braking hard on its own (pleasant single "ting", once per braking)
  warning - braking is needed but the system will not (or cannot) brake: the driver must brake (harsh, repeats)

Pure logic (no cereal), fed with plain values by the longitudinal planner at 20 Hz.
"""
from dataclasses import dataclass

DT = 0.05  # plannerd runs at 20 Hz

# chime: sunnypilot commanding a strong deceleration
CHIME_ACCEL = -2.0          # m/s^2, commanded accel at or below this counts as hard braking
CHIME_ON_TIME = 0.3         # s, held this long before the chime plays
CHIME_REARM_ACCEL = -1.0    # m/s^2, braking is over once accel is above this ...
CHIME_REARM_TIME = 3.0      # s, ... for this long
CHIME_MIN_SPEED = 3.0       # m/s, ignore the stopping accel openpilot commands near standstill

# warning: lead car closing in
LEAD_GAP = 5.0              # m, distance kept to the lead when computing required decel
LEAD_REQ_OWN = 2.5          # m/s^2, required decel that warns when sunnypilot does not control speed
LEAD_REQ_OP = 4.0           # m/s^2, required decel beyond what sunnypilot long can brake
LEAD_MIN_SPEED = 3.0        # m/s, no lead warnings while creeping in traffic

# warning: model predicts a stop (red light / stop line) that the car will not brake for
STOP_MIN_SPEED = 8.0        # m/s (~30 km/h), below this the driver is clearly handling the stop
STOP_TIME = 1.5             # s, condition must hold this long before warning

# warning: speed camera / bump ahead, too fast, and the car is not slowing for it
CARROT_TIME = 5.0           # s to the item
CARROT_CAM_MARGIN = 3.0     # km/h over the camera limit
CARROT_BUMP_MARGIN = 10.0   # km/h over the bump speed

NOT_DECELERATING = -0.3     # m/s^2, aEgo above this means nobody is braking
WARNING_HOLD = 1.0          # s, warning keeps sounding this long after the condition clears

SPD_TYPE_BUMP = 22
SPD_TYPE_SECTION = 4


@dataclass
class BrakeInputs:
  v_ego: float = 0.
  a_ego: float = 0.
  brake_pressed: bool = False
  long_active: bool = False          # sunnypilot controls speed (rainbow border)
  experimental: bool = False
  accel_cmd: float = 0.              # carControl.actuators.accel
  has_lead: bool = False
  lead_d: float = 0.
  lead_v: float = 0.
  model_stop: bool = False           # model speed at the end of its horizon ~ 0
  carrot_item: bool = False          # camera / section / bump being approached
  carrot_type: int = -1
  carrot_limit: int = 0              # km/h, camera limit (bump speed for bumps)
  carrot_dist: float = 0.            # m
  carrot_braking: bool = False       # sunnypilot is slowing for the item


def lead_required_decel(v_ego: float, lead_d: float, lead_v: float) -> float:
  v_rel = v_ego - lead_v
  if v_rel <= 0.:
    return 0.
  return v_rel ** 2 / (2. * max(lead_d - LEAD_GAP, 0.5))


class BrakeAlerts:
  def __init__(self):
    self.chime = False
    self.warning = False
    self._hard_t = 0.
    self._rearm_t = 0.
    self._chime_armed = True
    self._stop_t = 0.
    self._warning_hold_t = 0.

  def _update_chime(self, i: BrakeInputs) -> bool:
    if i.long_active and i.accel_cmd <= CHIME_ACCEL and i.v_ego > CHIME_MIN_SPEED:
      self._hard_t += DT
    else:
      self._hard_t = 0.

    if not i.long_active or i.accel_cmd > CHIME_REARM_ACCEL:
      self._rearm_t += DT
    else:
      self._rearm_t = 0.
    if self._rearm_t >= CHIME_REARM_TIME:
      self._chime_armed = True

    if self._chime_armed and self._hard_t >= CHIME_ON_TIME:
      self._chime_armed = False
      return True
    return False

  def _need_brake(self, i: BrakeInputs) -> bool:
    if i.brake_pressed:
      self._stop_t = 0.
      return False

    # lead closing in faster than the system will brake for
    if i.has_lead and i.v_ego > LEAD_MIN_SPEED:
      a_req = lead_required_decel(i.v_ego, i.lead_d, i.lead_v)
      limit = LEAD_REQ_OP if i.long_active else LEAD_REQ_OWN
      if a_req > limit and i.a_ego > -0.7 * a_req:
        return True

    # stop ahead without a car (red light / stop line), only Experimental op long brakes for it
    near_lead = i.has_lead and i.lead_d < 50.
    stop_unhandled = i.model_stop and not near_lead and not (i.long_active and i.experimental)
    if stop_unhandled and i.v_ego > STOP_MIN_SPEED and i.a_ego > NOT_DECELERATING:
      self._stop_t += DT
    else:
      self._stop_t = 0.
    if self._stop_t >= STOP_TIME:
      return True

    # speed camera / bump close ahead, too fast, and nothing is slowing the car
    if i.carrot_item and not i.carrot_braking and i.carrot_dist > 0. and i.v_ego > 1.:
      v_kph = i.v_ego * 3.6
      target = None
      if i.carrot_limit > 0 and i.carrot_type != SPD_TYPE_SECTION:
        target = i.carrot_limit + (CARROT_BUMP_MARGIN if i.carrot_type == SPD_TYPE_BUMP else CARROT_CAM_MARGIN)
      if target is not None and v_kph > target and i.carrot_dist / i.v_ego < CARROT_TIME and i.a_ego > NOT_DECELERATING:
        return True

    return False

  def update(self, i: BrakeInputs) -> None:
    self.chime = self._update_chime(i)

    if self._need_brake(i):
      self._warning_hold_t = WARNING_HOLD
    else:
      self._warning_hold_t = max(0., self._warning_hold_t - DT)
    self.warning = self._warning_hold_t > 0. and not i.brake_pressed
    if self.warning:
      self.chime = False
