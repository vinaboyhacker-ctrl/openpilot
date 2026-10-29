"""
Top-center stop indicator for the mici HUD.

The driving model does not classify traffic-light colors. This only shows what the planner/model
intends, so the driver knows whether the car is about to stop on its own:
  filled red    - model plans a stop (red light / stop line) and op long + Experimental will brake
  red ring      - model sees a stop ahead, but the car will NOT brake for it (no op long / not Experimental)
  filled amber  - op long is stopping behind a stopped/slow car ahead
"""
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state

MODEL_STOP_V = 1.0       # m/s, model's speed at the end of its ~10 s horizon
LEAD_STOP_V = 1.0        # m/s, lead considered stopped
LEAD_STOP_DIST = 80.     # m
RADIUS = 20

RED = (255, 40, 40)
AMBER = (255, 170, 0)


class StopIndicator:
  def __init__(self):
    self._alpha = FirstOrderFilter(0., 0.15, 1 / 20)
    self._color = RED
    self._filled = True

  def update(self) -> None:
    show = False
    try:
      sm = ui_state.sm
      long_active = bool(sm['carControl'].longActive)
      experimental = bool(sm['selfdriveState'].experimentalMode)
      lead = sm['radarState'].leadOne
      model_v = sm['modelV2'].velocity.x
      model_stop = len(model_v) > 0 and model_v[-1] < MODEL_STOP_V
      lead_stop = bool(lead.status) and lead.vLead < LEAD_STOP_V and lead.dRel < LEAD_STOP_DIST

      if long_active and lead_stop:
        show, self._color, self._filled = True, AMBER, True
      elif model_stop and not lead_stop:
        show, self._color, self._filled = True, RED, long_active and experimental
    except Exception:
      show = False
    self._alpha.update(1. if show else 0.)

  def render(self, rect: rl.Rectangle, alert_active: bool = False) -> None:
    a = int(255 * self._alpha.x)
    if a < 5:
      return
    # top-center normally; top-right while an alert's text occupies the top-left/center
    cx = int(rect.x + rect.width - RADIUS - 18) if alert_active else int(rect.x + rect.width / 2)
    cy = int(rect.y + RADIUS + 14)
    color = rl.Color(*self._color, a)
    if self._filled:
      rl.draw_circle(cx, cy, RADIUS + 3, rl.Color(0, 0, 0, int(a * 0.6)))
      rl.draw_circle(cx, cy, RADIUS, color)
    else:
      rl.draw_ring(rl.Vector2(cx, cy), RADIUS - 6, RADIUS, 0, 360, 36, color)
