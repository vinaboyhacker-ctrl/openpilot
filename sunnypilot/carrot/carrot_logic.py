"""
Pure navigation -> target speed logic, ported from CarrotPilot's CarrotServ.

No openpilot imports here so it can be unit tested anywhere. All speeds are km/h unless noted.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

NO_LIMIT_KPH = 250.0

# Seconds without app data before the navigation source is considered disconnected (10 Hz steps).
ACTIVE_COUNT_MAX = 80      # 8 s since the last message of any kind
ACTIVE_SDI_COUNT_MAX = 200  # 20 s since the last guidance (rgdata) message

# TMAP SDI (Safety Driving Information) types that carry an enforced speed limit
SDI_SPEED_CAMERA_TYPES = (0, 1, 2, 3, 4, 7, 8, 75, 76)
SDI_MOBILE_CAMERA = 7
SDI_SPEED_BUMP = 22
SDI_SECTION_ACTIVE = 4  # synthetic type used while inside a section (average speed) enforcement

# TBT turn types -> (navType, modifier, xTurnInfo)
# xTurnInfo: 1 left turn, 2 right turn, 3 left fork/exit, 4 right fork/exit, 5 rotary, 6 tollgate, 7 u-turn, 8 arrive
TURN_TYPE_MAPPING = {
  12: ("turn", "left", 1), 16: ("turn", "sharp left", 1),
  13: ("turn", "right", 2), 19: ("turn", "sharp right", 2),
  102: ("off ramp", "slight left", 3), 105: ("off ramp", "slight left", 3),
  112: ("off ramp", "slight left", 3), 115: ("off ramp", "slight left", 3),
  101: ("off ramp", "slight right", 4), 104: ("off ramp", "slight right", 4),
  111: ("off ramp", "slight right", 4), 114: ("off ramp", "slight right", 4),
  7: ("fork", "left", 3), 44: ("fork", "left", 3), 17: ("fork", "left", 3), 75: ("fork", "left", 3),
  76: ("fork", "left", 3), 118: ("fork", "left", 3),
  6: ("fork", "right", 4), 43: ("fork", "right", 4), 73: ("fork", "right", 4), 74: ("fork", "right", 4),
  123: ("fork", "right", 4), 124: ("fork", "right", 4), 117: ("fork", "right", 4),
  131: ("rotary", "slight right", 5), 132: ("rotary", "slight right", 5),
  140: ("rotary", "slight left", 5), 141: ("rotary", "slight left", 5),
  133: ("rotary", "right", 5), 134: ("rotary", "sharp right", 5), 135: ("rotary", "sharp right", 5),
  136: ("rotary", "sharp left", 5), 137: ("rotary", "sharp left", 5), 138: ("rotary", "sharp left", 5),
  139: ("rotary", "left", 5), 142: ("rotary", "straight", 5),
  14: ("turn", "uturn", 7),
  201: ("arrive", "straight", 8),
  51: ("notification", "straight", 0), 52: ("notification", "straight", 0), 53: ("notification", "straight", 0),
  54: ("notification", "straight", 0), 55: ("notification", "straight", 0),
  153: ("", "", 6), 154: ("", "", 6), 249: ("", "", 6),
}

SDI_DESCR_EN = {
  0: "Signal/speed camera", 1: "Speed camera", 2: "Section start", 3: "Section end", 4: "Section enforcement",
  5: "Tailgating camera", 6: "Signal camera", 7: "Mobile camera", 8: "Speed risk zone", 9: "Bus lane",
  20: "School zone start", 21: "School zone end", 22: "Speed bump", 26: "Toll gate", 30: "Sharp curve",
  75: "Rear speed camera", 76: "Rear signal/speed camera",
}


@dataclass
class CarrotSettings:
  # 0: off, 1: fixed cameras, 2: + speed bumps, 3: + mobile cameras
  speed_ctrl_mode: int = 2
  safety_factor: float = 1.05     # camera limit multiplier
  decel_rate: float = 1.2         # m/s^2 used for the approach profile
  speed_ctrl_end_s: float = 6.0   # reach the target this many seconds before the camera
  bump_speed: float = 35.0
  bump_time_s: float = 1.0
  road_limit_offset: int = -1     # -1: do not follow the road limit, otherwise limit + offset
  turn_speed: float = 0.0         # 0: off, otherwise slow to this speed for TBT turns
  turn_end_s: float = 6.0
  is_metric: bool = True


def calculate_current_speed(left_dist: float, safe_speed_kph: float, safe_time: float, decel_rate: float) -> float:
  """Highest speed now that still allows reaching safe_speed_kph, safe_time seconds before the point."""
  safe_speed = safe_speed_kph / 3.6
  decel_dist = left_dist - safe_speed * safe_time
  if decel_dist <= 0:
    return safe_speed_kph
  temp = safe_speed ** 2 + 2 * decel_rate * decel_dist
  speed_mps = math.sqrt(temp) if temp > 0 else safe_speed
  return max(safe_speed_kph, min(NO_LIMIT_KPH, speed_mps * 3.6))


def _i(v, default=0) -> int:
  try:
    return default if v is None else int(float(v))
  except (TypeError, ValueError):
    return default


def _f(v, default=0.0) -> float:
  try:
    return default if v is None else float(v)
  except (TypeError, ValueError):
    return default


def _s(v, default="") -> str:
  if v is None:
    return default
  s = str(v)
  return "" if s == "null" else s


def normalize_rgdata(rgdata):
  """Newer app versions nest the fields in guidance/sdi/lane groups; flatten them."""
  if not isinstance(rgdata, dict):
    return rgdata
  merged = dict(rgdata)
  for group_key in ("guidance", "sdi", "lane"):
    group = rgdata.get(group_key)
    if isinstance(group, dict):
      for key, value in group.items():
        merged.setdefault(key, value)
  return merged


@dataclass
class CarrotOutput:
  active: int = 0                 # 0 none, 1 app connected, 2 guidance, 3 camera decel, 4 section, 5 bump
  connected: bool = False
  desired_speed: float = NO_LIMIT_KPH
  desired_source: str = "none"
  road_limit_speed: int = 0
  spd_type: int = -1
  spd_limit: int = 0
  spd_dist: int = 0
  spd_countdown: int = 100
  turn_info: int = -1
  dist_to_turn: int = 0
  road_name: str = ""
  tbt_text: str = ""
  sdi_descr: str = ""
  go_pos_dist: int = 0
  go_pos_time: int = 0
  lat: float = 0.0
  lon: float = 0.0
  heading: float = 0.0


@dataclass
class CarrotNaviState:
  settings: CarrotSettings = field(default_factory=CarrotSettings)

  def __post_init__(self):
    self.active_count = 0
    self.active_sdi_count = 0

    self.n_road_limit_speed = 30
    self._road_limit_pending = 0
    self.road_limit_received = False

    self.n_sdi_type = -1
    self.n_sdi_speed_limit = 0
    self.n_sdi_dist = 0
    self.n_sdi_block_type = -1
    self.n_sdi_block_dist = 0
    self.n_sdi_plus_type = -1
    self.n_sdi_plus_dist = 0
    self.roadcate = 8

    self.n_tbt_dist = 0
    self.n_tbt_turn_type = -1
    self.n_tbt_next_road_width = 0
    self.sz_tbt_main_text = ""
    self.sz_pos_road_name = ""
    self.n_go_pos_dist = 0
    self.n_go_pos_time = 0
    self.lat = 0.0
    self.lon = 0.0
    self.heading = 0.0

    # Derived, decremented by the distance driven between messages
    self.x_spd_limit = 0.0
    self.x_spd_dist = 0.0
    self.x_spd_type = -1
    self.x_spd_slow = False  # alert is always shown; this says whether "Slow Down For" also slows for it
    self.x_turn_info = -1
    self.x_dist_to_turn = 0.0

    self.gas_override_speed = 0.0
    self.gas_pressed_last = False
    self.source_last = "none"
    self.countdown_dist_last = 0.0
    self.left_spd_sec = 100

  # ---------------------------------------------------------------- input
  def update_json(self, data: dict) -> None:
    """Apply one CarrotMan state message (UDP json or normalized HTTP/TCP rgdata)."""
    if not isinstance(data, dict):
      return
    self.active_count = ACTIVE_COUNT_MAX

    if "nRoadLimitSpeed" not in data:
      return

    self.active_sdi_count = ACTIVE_SDI_COUNT_MAX
    road_limit = _i(data.get("nRoadLimitSpeed"), 20)
    if road_limit > 0:
      if road_limit > 200:
        road_limit = int((road_limit - 20) / 10)
      elif road_limit == 120:
        road_limit = 115  # same workaround as CarrotPilot ("120 -> 115 fix bug")
    else:
      road_limit = 30
    # Debounce: require a few consistent messages before switching the road limit
    if road_limit != self.n_road_limit_speed:
      self._road_limit_pending += 1
      if self._road_limit_pending > 5 or not self.road_limit_received:
        self.n_road_limit_speed = road_limit
        self._road_limit_pending = 0
    else:
      self._road_limit_pending = 0
    self.road_limit_received = True

    self.n_sdi_type = _i(data.get("nSdiType"), -1)
    self.n_sdi_speed_limit = _i(data.get("nSdiSpeedLimit"), 0)
    self.n_sdi_dist = _i(data.get("nSdiDist"), -1)
    self.n_sdi_block_type = _i(data.get("nSdiBlockType"), -1)
    self.n_sdi_block_dist = _i(data.get("nSdiBlockDist"), 0)
    self.n_sdi_plus_type = _i(data.get("nSdiPlusType"), -1)
    self.n_sdi_plus_dist = _i(data.get("nSdiPlusDist"), 0)
    self.roadcate = _i(data.get("roadcate"), 0)

    self.n_tbt_dist = _i(data.get("nTBTDist"), 0)
    self.n_tbt_turn_type = _i(data.get("nTBTTurnType"), -1)
    self.n_tbt_next_road_width = _i(data.get("nTBTNextRoadWidth"), 0)
    self.sz_tbt_main_text = _s(data.get("szTBTMainText"))
    self.sz_pos_road_name = _s(data.get("szPosRoadName"))
    self.n_go_pos_dist = _i(data.get("nGoPosDist"), 0)
    self.n_go_pos_time = _i(data.get("nGoPosTime"), 0)

    lat = _f(data.get("vpPosPointLat"), 0.0)
    if lat != 0.0:
      self.lat = lat
      self.lon = _f(data.get("vpPosPointLon"), 0.0)
      self.heading = _f(data.get("nPosAngle"), self.heading)

    self._update_tbt()
    self._update_sdi()

  def _update_tbt(self) -> None:
    _, _, self.x_turn_info = TURN_TYPE_MAPPING.get(self.n_tbt_turn_type, ("invalid", "", -1))
    if self.n_tbt_dist > 0 and self.x_turn_info > 0:
      self.x_dist_to_turn = float(self.n_tbt_dist)

  def _update_sdi(self) -> None:
    """Cameras / sections / bumps are always detected (so the alert icon shows);
    `CarrotNaviSpeedCtrlMode` only decides which of them the car also slows down for:
    0 alerts only, 1 cameras, 2 + bumps, 3 + mobile cameras."""
    s = self.settings
    if self.n_sdi_type in SDI_SPEED_CAMERA_TYPES and self.n_sdi_speed_limit > 0:
      self.x_spd_limit = self.n_sdi_speed_limit * s.safety_factor
      self.x_spd_dist = float(self.n_sdi_dist)
      self.x_spd_type = self.n_sdi_type
      self.x_spd_slow = s.speed_ctrl_mode >= 1
      if self.n_sdi_block_type in (2, 3):  # inside / ending a section enforcement
        self.x_spd_dist = float(self.n_sdi_block_dist)
        self.x_spd_type = SDI_SECTION_ACTIVE
      elif self.n_sdi_type == SDI_MOBILE_CAMERA:
        self.x_spd_slow = s.speed_ctrl_mode >= 3
    elif SDI_SPEED_BUMP in (self.n_sdi_plus_type, self.n_sdi_type):
      self.x_spd_limit = s.bump_speed
      self.x_spd_dist = float(self.n_sdi_plus_dist if self.n_sdi_plus_type == SDI_SPEED_BUMP else self.n_sdi_dist)
      self.x_spd_type = SDI_SPEED_BUMP
      # never slow for "bumps" on highways (roadcate 0/1)
      self.x_spd_slow = s.speed_ctrl_mode >= 2 and self.roadcate > 1
    else:
      self.x_spd_limit = 0
      self.x_spd_type = -1
      self.x_spd_dist = 0
      self.x_spd_slow = False

  # ---------------------------------------------------------------- step
  def _turn_speed(self, x_turn_info: int, dist: float) -> float:
    s = self.settings
    if s.turn_speed <= 0 or dist <= 0:
      return NO_LIMIT_KPH
    if x_turn_info in (1, 2, 5):
      speed = s.turn_speed
    elif x_turn_info in (3, 4, 6):
      speed = float(self.n_road_limit_speed)
    elif x_turn_info in (7, 8):
      speed = 1.0
    else:
      return NO_LIMIT_KPH
    end_dist = 5.0 if x_turn_info in (7, 8) else s.turn_end_s * speed / 3.6
    return calculate_current_speed(dist - end_dist, speed, 2.0, s.decel_rate)

  def step(self, v_ego: float, delta_dist: float, gas_pressed: bool = False, brake_pressed: bool = False) -> CarrotOutput:
    """Advance one 10 Hz step. v_ego in m/s, delta_dist in m driven since the last step."""
    s = self.settings
    v_ego_kph = v_ego * 3.6
    out = CarrotOutput()

    delta_dist = max(0.0, delta_dist)
    self.x_spd_dist = max(self.x_spd_dist - delta_dist, -1000.0)
    self.x_dist_to_turn -= delta_dist
    self.active_count = max(self.active_count - 1, 0)
    self.active_sdi_count = max(self.active_sdi_count - 1, 0)

    active = 0
    if self.active_count > 0:
      active = 2 if self.active_sdi_count > 0 else 1
    out.connected = self.active_count > 0

    if active <= 1:
      self.x_spd_type = self.x_turn_info = -1
      self.x_spd_limit = 0
      self.n_sdi_type = -1
      self.n_tbt_turn_type = -1
      self.roadcate = 8
      self.n_go_pos_dist = 0

    if self.x_spd_type < 0 or self.x_spd_dist <= 0:
      self.x_spd_type = -1
      self.x_spd_dist = self.x_spd_limit = 0
      self.x_spd_slow = False
    if self.x_turn_info < 0 or self.x_dist_to_turn < -50:
      self.x_dist_to_turn = min(self.x_dist_to_turn, 0.0)
      self.x_turn_info = -1

    # Road speed limit (+ offset)
    limit_speed = NO_LIMIT_KPH
    if s.road_limit_offset >= 0 and active >= 2 and self.n_road_limit_speed >= 30:
      offset = s.road_limit_offset if s.is_metric else s.road_limit_offset * 1.609344  # offset entered in mph
      limit_speed = self.n_road_limit_speed + offset

    # Speed cameras, section enforcement, speed bumps
    sdi_speed = NO_LIMIT_KPH
    if self.x_spd_limit > 0 and self.x_spd_dist > 0 and active > 0:
      is_bump = self.x_spd_type == SDI_SPEED_BUMP
      safe_sec = s.bump_time_s if is_bump else s.speed_ctrl_end_s
      sdi_speed = calculate_current_speed(self.x_spd_dist, self.x_spd_limit, safe_sec, s.decel_rate)
      active = 5 if is_bump else 3
      if self.x_spd_type == SDI_SECTION_ACTIVE:
        sdi_speed = self.x_spd_limit
        active = 4
      if not self.x_spd_slow:
        sdi_speed = NO_LIMIT_KPH  # alert only
    sdi_source = "bump" if self.x_spd_type == SDI_SPEED_BUMP else "section" if self.x_spd_type == SDI_SECTION_ACTIVE else "cam"

    turn_speed = self._turn_speed(self.x_turn_info, self.x_dist_to_turn)

    desired_speed, source = min(((turn_speed, "turn"), (sdi_speed, sdi_source), (limit_speed, "road")), key=lambda x: x[0])
    if desired_speed >= NO_LIMIT_KPH:
      source = "none"

    desired_speed, source = self._apply_gas_override(desired_speed, source, v_ego, v_ego_kph, gas_pressed, brake_pressed)

    # Countdown (seconds to the camera / bump)
    if self.x_spd_dist > 0:
      self.left_spd_sec = int(max(self.x_spd_dist - v_ego, 1) / max(1.0, v_ego) + 0.5)
    else:
      self.left_spd_sec = 100

    out.active = active
    out.desired_speed = float(desired_speed)
    out.desired_source = source
    out.road_limit_speed = int(self.n_road_limit_speed) if active >= 2 else 0
    out.spd_type = int(self.x_spd_type)
    out.spd_limit = int(self.x_spd_limit)
    out.spd_dist = int(self.x_spd_dist)
    out.spd_countdown = int(self.left_spd_sec)
    out.turn_info = int(self.x_turn_info)
    out.dist_to_turn = int(self.x_dist_to_turn)
    out.road_name = self.sz_pos_road_name
    out.tbt_text = self.sz_tbt_main_text
    out.sdi_descr = SDI_DESCR_EN.get(self.x_spd_type if self.x_spd_type >= 0 else self.n_sdi_type, "")
    out.go_pos_dist = self.n_go_pos_dist
    out.go_pos_time = self.n_go_pos_time
    out.lat, out.lon, out.heading = self.lat, self.lon, self.heading
    return out

  def _apply_gas_override(self, desired_speed, source, v_ego, v_ego_kph, gas_pressed, brake_pressed):
    """Carrot behaviour: pressing the gas lifts road-limit / bump / turn slowdowns to the speed reached.
    Fixed cameras and section enforcement are never overridden by the gas pedal."""
    gas_rising = gas_pressed and not self.gas_pressed_last
    self.gas_pressed_last = gas_pressed

    if source != self.source_last:
      self.gas_override_speed = 0.0
    self.source_last = source

    if v_ego < 0.1 or desired_speed > 150 or source in ("cam", "section") or brake_pressed:
      self.gas_override_speed = 0.0
    elif self.gas_override_speed <= 0:
      if gas_rising and desired_speed < v_ego_kph:
        self.gas_override_speed = v_ego_kph
    elif gas_pressed:
      self.gas_override_speed = max(v_ego_kph, self.gas_override_speed)

    if desired_speed < self.gas_override_speed:
      return self.gas_override_speed, "gas"
    return desired_speed, source
