"""
Lead / stop indicators for the mici HUD, drawn large at the top-right of the camera view
(readable on the phone UI stream). DISPLAY ONLY: reads messages, never changes braking, throttle or steering.

The driving model does not classify traffic-light colors. The stop icon only shows what the
model/planner intends:
  LEAD icon (car seen from behind) + distance (m) + relative speed (km/h)
    green  = far,  amber = closing / near,  red = very near (TTC < 3 s)
  STOP icon (traffic light)
    red light, filled  "DUNG"  = model/planner wants to stop AND sunnypilot will brake (E2E / DEC blended)
    red ring, hollow   "DUNG?" = model sees a stop but sunnypilot will NOT brake for it (DEC in ACC,
                                  Chill, or long not active): the driver must brake
    nothing                    = the car does not intend to stop -> brake yourself if needed

Backup / restore: see /data/backup_ui_20261114/HUONG_DAN.txt
"""
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state

# hysteresis (enter / exit) so icons do not flicker around one threshold
MODEL_STOP_V_ON, MODEL_STOP_V_OFF = 1.0, 2.0   # m/s, model speed at the end of its horizon
LEAD_STOP_V_ON, LEAD_STOP_V_OFF = 1.0, 2.0     # m/s, lead speed
LEAD_NEAR_DIST = 50.                           # m, a stop is "because of the car ahead"
LEAD_SHOW_DIST = 120.                          # m, show the lead icon within this
TTC_RED, TTC_AMBER = 3.0, 6.0                  # s
DIST_RED = 8.0                                 # m, always red closer than this while moving

RED = (255, 40, 40)
AMBER = (255, 170, 0)
GREEN = (40, 220, 90)
GRAY = (90, 90, 90)
BOX_W = 112                                    # px, width of the big icon boxes


def _font():
  from openpilot.system.ui.lib.application import gui_app, FontWeight
  return gui_app.font(FontWeight.BOLD)


def _text_c(txt, cx, y, size, color):
  f = _font()
  m = rl.measure_text_ex(f, txt, size, 0)
  rl.draw_text_ex(f, txt, rl.Vector2(cx - m.x / 2, y), size, 0, color)


class StopIndicator:
  def __init__(self):
    self._lead_alpha = FirstOrderFilter(0., 0.1, 1 / 60)
    self._stop_alpha = FirstOrderFilter(0., 0.1, 1 / 60)
    self._d_filt = FirstOrderFilter(0., 0.2, 1 / 60)
    self._v_filt = FirstOrderFilter(0., 0.3, 1 / 60)
    self._model_stop = False
    self._lead_stop = False
    self._lead_color = GREEN
    self._stop_will_brake = False

  # ---------------------------------------------------------------- state
  def update(self) -> None:
    show_lead = show_stop = False
    try:
      sm = ui_state.sm
      long_active = bool(sm['carControl'].longActive)
      experimental = bool(sm['selfdriveState'].experimentalMode)
      lead = sm['radarState'].leadOne
      has_lead = bool(lead.status) and sm.valid['radarState']
      v_ego = float(sm['carState'].vEgo)

      # DEC: in ACC sub-mode the model's stop is NOT used for braking
      e2e_active = experimental
      try:
        dec = sm['longitudinalPlanSP'].dec
        if experimental and dec.active and str(dec.state) != "blended":
          e2e_active = False
      except Exception:
        pass

      # --- lead icon
      if has_lead and lead.dRel < LEAD_SHOW_DIST:
        show_lead = True
        d, v_rel = float(lead.dRel), float(lead.vRel)
        if self._lead_alpha.x < 0.05:
          self._d_filt.x, self._v_filt.x = d, v_rel
        self._d_filt.update(d)
        self._v_filt.update(v_rel)
        ttc = d / -v_rel if v_rel < -0.3 else 99.
        moving = v_ego > 0.5
        if (ttc < TTC_RED) or (moving and d < max(DIST_RED, v_ego * 0.8)):
          self._lead_color = RED
        elif ttc < TTC_AMBER or d < max(DIST_RED, v_ego * 1.5) or not moving:
          self._lead_color = AMBER
        else:
          self._lead_color = GREEN
        self._lead_stop = lead.vLead < (LEAD_STOP_V_OFF if self._lead_stop else LEAD_STOP_V_ON)
      else:
        self._lead_stop = False

      # --- stop intent (model / planner)
      model = sm['modelV2']
      model_v = model.velocity.x
      if len(model_v) > 0:
        self._model_stop = float(model_v[-1]) < (MODEL_STOP_V_OFF if self._model_stop else MODEL_STOP_V_ON)
      else:
        self._model_stop = False
      try:
        action_stop = bool(model.action.shouldStop)
      except Exception:
        action_stop = False
      plan_stop = bool(sm['longitudinalPlan'].shouldStop)
      wants_stop = self._model_stop or action_stop or plan_stop

      # a stop explained by a slow car close ahead is shown by the lead icon only
      lead_explains = has_lead and lead.dRel < LEAD_NEAR_DIST and self._lead_stop
      if wants_stop and not lead_explains:
        show_stop = True
        self._stop_will_brake = long_active and (e2e_active or plan_stop)
    except Exception:
      show_lead = show_stop = False
    self._lead_alpha.update(1. if show_lead else 0.)
    self._stop_alpha.update(1. if show_stop else 0.)

  def render(self, rect: rl.Rectangle, alert_active: bool = False) -> None:
    """Big icons stacked at the top-right corner of the camera view (readable on the phone stream)."""
    x = rect.x + rect.width - BOX_W - 8
    y = rect.y + 8
    try:
      a = int(255 * min(max(self._lead_alpha.x, 0.), 1.))
      if a >= 5:
        y = self._draw_lead_box(x, y, a) + 6
    except Exception:
      pass
    try:
      a = int(255 * min(max(self._stop_alpha.x, 0.), 1.))
      if a >= 5:
        self._draw_stop_box(x, y, a)
    except Exception:
      pass

  def render_side(self, cr: rl.Rectangle, top_y: float) -> float:
    # icons moved to the camera view (render); nothing drawn in the side panel any more
    return top_y

  def _box(self, x, y, h, a):
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, BOX_W, h), 0.25, 10, rl.Color(0, 0, 0, int(170 * a / 255)))

  def _draw_lead_box(self, x, y, a) -> float:
    h = 108
    self._box(x, y, h, a)
    mx = x + BOX_W / 2
    col = rl.Color(*self._lead_color, a)
    self._draw_car(mx, y + 26, col, a)
    d = max(self._d_filt.x, 0.)
    _text_c(f"{d:.0f}m", mx, y + 48, 34, rl.Color(255, 255, 255, a))
    v_kmh = self._v_filt.x * 3.6
    vtxt = f"{v_kmh:+.0f} km/h" if abs(v_kmh) >= 1 else "0 km/h"
    _text_c(vtxt, mx, y + 82, 20, col)
    return y + h

  def _draw_stop_box(self, x, y, a) -> float:
    h = 76
    self._box(x, y, h, a)
    mx = x + BOX_W / 2
    red = rl.Color(*RED, a)
    cy = y + 22
    rl.draw_rectangle_rounded(rl.Rectangle(mx - 42, y + 6, 84, 32), 0.6, 10, rl.Color(40, 40, 40, a))
    if self._stop_will_brake:
      rl.draw_circle(int(mx - 24), int(cy), 13, red)
    else:
      rl.draw_ring(rl.Vector2(mx - 24, cy), 8, 13, 0, 360, 32, red)
    rl.draw_circle(int(mx), int(cy), 10, rl.Color(*GRAY, a))
    rl.draw_circle(int(mx + 24), int(cy), 10, rl.Color(*GRAY, a))
    if self._stop_will_brake:
      _text_c("DUNG", mx, y + 42, 28, red)
    else:
      _text_c("DUNG?", mx, y + 42, 28, rl.Color(*AMBER, a))
    return y + h

  def _draw_car(self, cx, cy, color, a) -> None:
    """Car seen from behind, ~60 px wide, ~44 px tall centered on (cx, cy)."""
    body = rl.Rectangle(cx - 30, cy - 2, 60, 20)
    cabin = rl.Rectangle(cx - 20, cy - 20, 40, 20)
    rl.draw_rectangle(int(cx - 26), int(cy + 16), 12, 8, color)   # wheels
    rl.draw_rectangle(int(cx + 14), int(cy + 16), 12, 8, color)
    rl.draw_rectangle_rounded(cabin, 0.4, 8, color)
    rl.draw_rectangle_rounded(body, 0.35, 8, color)
    rl.draw_rectangle_rounded(rl.Rectangle(cx - 14, cy - 16, 28, 10), 0.3, 6, rl.Color(0, 0, 0, int(a * 0.45)))
    light = rl.Color(255, 235, 235, a)
    rl.draw_rectangle(int(cx - 26), int(cy + 4), 10, 6, light)    # tail lights
    rl.draw_rectangle(int(cx + 16), int(cy + 4), 10, 6, light)


# single shared instance: updated by HudRendererSP, drawn by ConfidenceBall in the side panel
INDICATOR = StopIndicator()
