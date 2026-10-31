"""
Minimal risk maneuver (MRM): what the car does when the driver stops responding.

Instead of cutting ACC and lane keeping, the car keeps them and:
  1. stop_in_lane - decelerates gently to a stop inside the lane (the default)
  2. to_shoulder  - when slow enough and the right blind spot is clear, shifts right onto the shoulder
                    while still decelerating, then stops there
  3. stopped      - standing still; nothing is commanded beyond holding the stop

Any sign that the driver is back (steering, gas, brake, or the monitoring level dropping) hands control
back immediately and returns to idle. A right blind spot detection during to_shoulder aborts the shift
and the car stops in lane.

Pure logic (no cereal). The planner / controls feed plain values in at 20 Hz.
"""
from dataclasses import dataclass
from enum import IntEnum

DT = 0.05                   # s, planner rate

MRM_DECEL = 1.5             # m/s^2, gentle stop
SHOULDER_MAX_V = 22.0       # m/s (~80 km/h): only move onto the shoulder at or below this speed
SHOULDER_CURV_MAX = -0.008  # 1/m, right-hand lane shift (negative curvature is right); tuned on car
SHOULDER_CURV_RATE = 0.0005 # 1/m per s, how fast the shift builds up (and unwinds on abort)
STOP_V = 0.1                # m/s, counts as stopped


class MrmState(IntEnum):
  idle = 0
  stop_in_lane = 1
  to_shoulder = 2
  stopped = 3


@dataclass
class MrmInputs:
  dm_terminal: bool = False         # driverMonitoringState alertLevel is three
  engaged: bool = False             # openpilot is controlling the car
  v_ego: float = 0.                 # m/s
  right_blindspot: bool = False
  left_blindspot: bool = False
  driver_steer_override: bool = False
  brake_pressed: bool = False
  gas_pressed: bool = False


class MinimalRiskManeuver:
  def __init__(self, allow_shoulder: bool = False):
    self.allow_shoulder = allow_shoulder  # off: stop in lane only
    self.state = MrmState.idle
    self.v_target = 0.              # m/s, decelerating profile
    self.curv_offset = 0.           # 1/m, added to the lane curvature

  @property
  def active(self) -> bool:
    return self.state != MrmState.idle

  def _reset(self) -> None:
    self.state = MrmState.idle
    self.v_target = 0.

  def update(self, i: MrmInputs) -> None:
    driver_back = i.driver_steer_override or i.gas_pressed or i.brake_pressed
    if not i.engaged or driver_back or not i.dm_terminal:
      self._reset()
      self.curv_offset = max(0., self.curv_offset - SHOULDER_CURV_RATE * DT) if self.curv_offset > 0 else \
        min(0., self.curv_offset + SHOULDER_CURV_RATE * DT)
      return

    if self.state == MrmState.idle:
      self.state = MrmState.stop_in_lane
      self.v_target = i.v_ego

    if self.state == MrmState.stopped:
      self.v_target = 0.
      return

    # decelerate the target from wherever it is now; never above the current speed
    self.v_target = max(0., min(self.v_target, i.v_ego) - MRM_DECEL * DT)

    if self.state == MrmState.stop_in_lane:
      self.curv_offset = min(0., self.curv_offset + SHOULDER_CURV_RATE * DT)
      if self.allow_shoulder and i.v_ego <= SHOULDER_MAX_V and not i.right_blindspot:
        self.state = MrmState.to_shoulder

    elif self.state == MrmState.to_shoulder:
      if i.right_blindspot:
        self.state = MrmState.stop_in_lane  # abort the shift, stop in lane
      else:
        self.curv_offset = max(SHOULDER_CURV_MAX, self.curv_offset - SHOULDER_CURV_RATE * DT)

    if self.state != MrmState.stopped and i.v_ego <= STOP_V:
      self.state = MrmState.stopped
      self.v_target = 0.
