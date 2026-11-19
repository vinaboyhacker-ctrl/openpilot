import math
import pyray as rl
from openpilot.selfdrive.ui.mici.onroad import SIDE_PANEL_WIDTH
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.lib.application import gui_app
from openpilot.common.filter_simple import FirstOrderFilter

from openpilot.selfdrive.ui.sunnypilot.mici.onroad.confidence_ball import ConfidenceBallSP


def draw_circle_gradient(center_x: float, center_y: float, radius: int,
                         top: rl.Color, bottom: rl.Color) -> None:
  # Draw a square with the gradient
  rl.draw_rectangle_gradient_v(int(center_x - radius), int(center_y - radius),
                               radius * 2, radius * 2,
                               top, bottom)

  # Paint over square with a ring
  outer_radius = math.ceil(radius * math.sqrt(2)) + 1
  rl.draw_ring(rl.Vector2(int(center_x), int(center_y)), radius, outer_radius,
               0.0, 360.0,
               20, rl.BLACK)


class ConfidenceBall(Widget, ConfidenceBallSP):
  def __init__(self, demo: bool = False):
    Widget.__init__(self)
    ConfidenceBallSP.__init__(self)
    self._demo = demo
    self._confidence_filter = FirstOrderFilter(-0.5, 0.5, 1 / gui_app.target_fps)

  def update_filter(self, value: float):
    self._confidence_filter.update(value)

  def _update_state(self):
    if self._demo:
      return

    # animate status dot in from bottom
    if ui_state.status == UIStatus.DISENGAGED:
      self._confidence_filter.update(-0.5)
    elif ui_state.status in (UIStatus.LAT_ONLY, UIStatus.LONG_ONLY):
      self._confidence_filter.update(1 - max(self.get_animate_status_probs() or [1]))
    else:
      self._confidence_filter.update((1 - max(ui_state.sm['modelV2'].meta.disengagePredictions.brakeDisengageProbs or [1])) *
                                                        (1 - max(ui_state.sm['modelV2'].meta.disengagePredictions.steerOverrideProbs or [1])))

  def _render(self, _):
    content_rect = rl.Rectangle(
      self.rect.x + self.rect.width - SIDE_PANEL_WIDTH,
      self.rect.y,
      SIDE_PANEL_WIDTH,
      self.rect.height,
    )

    status_dot_radius = 24
    dot_height = (1 - self._confidence_filter.x) * (content_rect.height - 2 * status_dot_radius) + status_dot_radius
    dot_height = self._rect.y + dot_height

    # confidence zones
    if ui_state.status == UIStatus.ENGAGED or self._demo:
      if self._confidence_filter.x > 0.5:
        top_dot_color = rl.Color(0, 255, 204, 255)
        bottom_dot_color = rl.Color(0, 255, 38, 255)
      elif self._confidence_filter.x > 0.2:
        top_dot_color = rl.Color(255, 200, 0, 255)
        bottom_dot_color = rl.Color(255, 115, 0, 255)
      else:
        top_dot_color = rl.Color(255, 0, 21, 255)
        bottom_dot_color = rl.Color(255, 0, 89, 255)

    elif ui_state.status in (UIStatus.LAT_ONLY, UIStatus.LONG_ONLY):
      top_dot_color = bottom_dot_color = self.get_lat_long_dot_color()

    elif ui_state.status == UIStatus.OVERRIDE:
      top_dot_color = rl.Color(255, 255, 255, 255)
      bottom_dot_color = rl.Color(82, 82, 82, 255)

    else:
      top_dot_color = rl.Color(50, 50, 50, 255)
      bottom_dot_color = rl.Color(13, 13, 13, 255)

    self._sp_render_extra(content_rect, dot_height, status_dot_radius, top_dot_color, bottom_dot_color)

  def _sp_render_extra(self, cr, dot_y, r, top, bottom):
    r = 22
    mx = cr.x + cr.width / 2
    cy = cr.y + r + 6
    try:
      self._sp_ball(mx, cy, r, top, bottom)
    except Exception:
      draw_circle_gradient(mx, cy, r, top, bottom)
    y = cr.y + 60
    try:
      y = self._sp_icons(cr, y) or y
    except Exception:
      pass
    try:
      from openpilot.selfdrive.ui.sunnypilot.mici.onroad.stop_indicator import INDICATOR
      INDICATOR.render_side(cr, y)
    except Exception:
      pass

  def _sp_ball(self, mx, cy, r, top, bottom):
    import colorsys
    def hsv(h, sa, v):
      c = colorsys.hsv_to_rgb(h % 1.0, sa, v)
      return rl.Color(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), 255)
    x = self._confidence_filter.x
    dt = 1.0 / gui_app.target_fps
    prev = getattr(self, '_sp_prev', x)
    self._sp_prev = x
    vel = (x - prev) / dt
    spd = getattr(self, '_sp_spd', 0.0) * 0.85 + abs(vel) * 0.15
    self._sp_spd = spd
    self._sp_phase = (getattr(self, '_sp_phase', 0.0) + dt * (0.1 + spd * 3.0)) % 1.0
    if not (ui_state.status == UIStatus.ENGAGED or self._demo):
      draw_circle_gradient(mx, cy, r, top, bottom)
      return
    mix = min(1.0, spd * 1.5)
    base = max(0.0, min(1.0, x)) * 0.36
    if vel < 0:
      h_move = self._sp_phase
    else:
      h_move = 0.33 + 0.07 * math.sin(self._sp_phase * 6.283)
    h = base + (h_move - base) * mix
    draw_circle_gradient(mx, cy, r, hsv(h, 0.85, 1.0), hsv(h + 0.05, 1.0, 0.8))

  def _sp_icons(self, cr, top_y):
    from openpilot.system.ui.lib.application import FontWeight
    cn = ui_state.sm['longitudinalPlanSP'].carrotNavi
    if not cn.enabled or cn.spdDist <= 0 or cn.spdType <= 0:
      return None
    src = (cn.source or '').lower()
    descr = (cn.sdiDescr or '').lower()
    kind = 'bump' if ('bump' in src or 'bump' in descr) else ('section' if 'section' in src else 'cam')
    d = cn.spdDist
    txt = f"{d / 1000:.1f}km" if d >= 1000 else f"{d}m"
    font = gui_app.font(FontWeight.BOLD)
    sz = 44
    fs = 18
    mx = cr.x + cr.width / 2
    cy = top_y + 4 + sz / 2
    rl.draw_rectangle_rounded(rl.Rectangle(cr.x + 2, top_y, cr.width - 4, sz + fs + 12), 0.3, 8, rl.Color(0, 0, 0, 160))
    if kind == 'bump':
      yb = cy + sz / 2 - 4
      rl.draw_triangle(rl.Vector2(mx, cy - sz / 2), rl.Vector2(mx - sz / 2, yb), rl.Vector2(mx + sz / 2, yb), rl.Color(230, 40, 30, 255))
      k = 7
      yi = yb - k * 0.6
      rl.draw_triangle(rl.Vector2(mx, cy - sz / 2 + k * 1.6), rl.Vector2(mx - sz / 2 + k, yi), rl.Vector2(mx + sz / 2 - k, yi), rl.Color(255, 210, 0, 255))
      rl.draw_circle_sector(rl.Vector2(mx, yi - 4), 8, 180, 360, 16, rl.BLACK)
      rl.draw_rectangle(int(mx - 12), int(yi - 4), 24, 3, rl.BLACK)
    else:
      ring = rl.Color(230, 40, 30, 255) if kind == 'cam' else rl.Color(255, 140, 0, 255)
      rl.draw_circle(int(mx), int(cy), sz / 2, ring)
      rl.draw_circle(int(mx), int(cy), sz / 2 - 5, rl.WHITE)
      lim = str(cn.spdLimit) if cn.spdLimit > 0 else '!'
      lfs = 20 if len(lim) < 3 else 16
      ls = rl.measure_text_ex(font, lim, lfs, 0)
      rl.draw_text_ex(font, lim, rl.Vector2(mx - ls.x / 2, cy - ls.y / 2), lfs, 0, rl.BLACK)
    ts = rl.measure_text_ex(font, txt, fs, 0)
    rl.draw_text_ex(font, txt, rl.Vector2(mx - ts.x / 2, cy + sz / 2 + 4), fs, 0, rl.WHITE)
    return top_y + sz + fs + 12 + 6  # next free y below the Carrot box


def sp_frame(b, colfn, y_from, rad, step):
  n = int(b.width)
  for i in range(0, n, step):
    dx = min(i, n - 1 - i)
    inset = 0.0
    if dx < rad:
      q = rad - dx - 0.5
      inset = rad - math.sqrt(max(0.0, rad * rad - q * q))
    t0 = max(b.y + inset, y_from)
    t1 = b.y + b.height - inset
    if t1 > t0:
      rl.draw_rectangle(int(b.x + i), int(t0), step, int(t1 - t0 + 0.5), colfn(i / max(1, n - 1)))


def sp_badge(b, mode):
  import colorsys
  from openpilot.system.ui.lib.application import FontWeight
  k = b.height / 34.0
  def rainbow(t):
    c = colorsys.hsv_to_rgb(t * 0.83, 1.0, 1.0)
    return rl.Color(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), 255)
  green = lambda t: rl.Color(46, 204, 64, 255)
  gray = lambda t: rl.Color(60, 60, 70, 255)
  chill = lambda t: rl.Color(int(230 - 190 * t), int(40 + 200 * t), int(240 - 150 * t), 255)
  rad = 7 * k
  st = max(1, int(k))
  if mode in ('E2E', 'DEC_E2E'):
    sp_frame(b, rainbow, b.y, rad, st)
  elif mode == 'CHILL':
    sp_frame(b, gray, b.y, rad, st)
    sp_frame(b, chill, b.y + b.height / 2, rad, st)
  else:
    sp_frame(b, green, b.y, rad, st)
  bw = 3 * k
  inner = rl.Rectangle(b.x + bw, b.y + bw, b.width - 2 * bw, b.height - 2 * bw)
  rl.draw_rectangle_rounded(inner, min(1.0, 2 * (rad - bw) / inner.height), 12, rl.Color(15, 15, 18, 235))
  font = gui_app.font(FontWeight.BOLD)
  mx = b.x + b.width / 2
  def text(t, size, cy, col):
    m = rl.measure_text_ex(font, t, size, 0)
    rl.draw_text_ex(font, t, rl.Vector2(mx - m.x / 2, cy - m.y / 2), size, 0, col)
  if mode.startswith('DEC'):
    text('DEC', 14 * k, b.y + 12 * k, rl.WHITE)
    if mode == 'DEC_ACC':
      text('ACC', 10 * k, b.y + 25 * k, rl.Color(46, 204, 64, 255))
    else:
      text('E2E', 10 * k, b.y + 25 * k, rl.Color(255, 200, 0, 255))
  else:
    text(mode, 18 * k, b.y + b.height / 2, rl.WHITE)
