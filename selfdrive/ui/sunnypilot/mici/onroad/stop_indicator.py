"""
Stop indicator for the mici HUD (top-center, or top-right while an alert is shown).

The driving model does not classify traffic-light colors. This only shows what the model/planner
intends, so the driver knows whether the car is about to stop on its own:
  filled red    - stop ahead without a car in front (red light / stop line), op long + Experimental will brake
  filled amber  - stopping behind a car ahead, op long will brake
  ring (red or amber) - a stop is expected, but the car will NOT brake for it: the driver must brake
"""
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state

# hysteresis (enter / exit) so the dot does not flicker around a single threshold
MODEL_STOP_V_ON, MODEL_STOP_V_OFF = 1.0, 2.0   # m/s, model speed at the end of its ~10 s horizon
LEAD_STOP_V_ON, LEAD_STOP_V_OFF = 1.0, 2.0     # m/s, lead speed
LEAD_STOP_DIST = 80.                           # m, stopped lead considered relevant
LEAD_NEAR_DIST = 50.                           # m, a stop is "because of the car ahead"
RADIUS = 20
MARGIN = 14

RED = (255, 40, 40)
AMBER = (255, 170, 0)


class StopIndicator:
  def __init__(self):
    self._alpha = FirstOrderFilter(0., 0.1, 1 / 60)
    self._model_stop = False
    self._lead_stop = False
    self._color = RED
    self._filled = True

  def update(self) -> None:
    show = False
    try:
      sm = ui_state.sm
      long_active = bool(sm['carControl'].longActive)
      experimental = bool(sm['selfdriveState'].experimentalMode)
      lead = sm['radarState'].leadOne
      has_lead = bool(lead.status)
      model_v = sm['modelV2'].velocity.x

      if len(model_v) > 0:
        v_end = float(model_v[-1])
        self._model_stop = v_end < (MODEL_STOP_V_OFF if self._model_stop else MODEL_STOP_V_ON)
      else:
        self._model_stop = False

      if has_lead and lead.dRel < LEAD_STOP_DIST:
        self._lead_stop = lead.vLead < (LEAD_STOP_V_OFF if self._lead_stop else LEAD_STOP_V_ON)
      else:
        self._lead_stop = False

      if self._model_stop or self._lead_stop:
        show = True
        if self._lead_stop or (has_lead and lead.dRel < LEAD_NEAR_DIST):
          # stopping behind a car: op long brakes for it in both Chill and Experimental
          self._color, self._filled = AMBER, long_active
        else:
          # stop without a car ahead (red light / stop line): only Experimental brakes for it
          self._color, self._filled = RED, long_active and experimental
    except Exception:
      show = False
    self._alpha.update(1. if show else 0.)

  def render(self, rect: rl.Rectangle, alert_active: bool = False) -> None:
    a = int(255 * min(max(self._alpha.x, 0.), 1.))
    if a < 5:
      return
    # top-center normally; top-right while an alert's text occupies the top-left/center
    cx = int(rect.x + rect.width - RADIUS - 18) if alert_active else int(rect.x + rect.width / 2)
    cy = int(rect.y + RADIUS + MARGIN)
    color = rl.Color(*self._color, a)
    rl.draw_circle(cx, cy, RADIUS + 3, rl.Color(0, 0, 0, int(a * 0.6)))
    if self._filled:
      rl.draw_circle(cx, cy, RADIUS, color)
    else:
      rl.draw_ring(rl.Vector2(cx, cy), RADIUS - 6, RADIUS, 0, 360, 36, color)
