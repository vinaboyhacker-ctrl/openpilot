from openpilot.system.ui.lib.application import gui_app, FontWeight
"""
Colored frame around the mici camera view that shows who controls speed:
  green - the car's own ACC (stock longitudinal) is engaged
  rainbow - sunnypilot longitudinal control is engaged (colors slowly flow around the frame):
            top half = sunnypilot End to End (follows the model, stops for lights),
            bottom half = sunnypilot ACC (follows set speed and the car ahead),
            bottom half + faint top half = Dynamic Experimental Control is in ACC and may switch to E2E by itself
  none  - nothing is controlling speed
"""
import colorsys
import math

import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state

BORDER_WIDTH = 6
CORNER_ROUNDNESS = 0.2 * 1.02   # matches the fake rounded border in augmented_road_view
GREEN = (40, 200, 90)
RAINBOW = "rainbow"
SEGMENTS_STRAIGHT = 16           # per long edge
SEGMENTS_CORNER = 8
RAINBOW_SPEED = 0.12             # turns around the frame per second


def _perimeter(rect: rl.Rectangle, radius: float) -> list[tuple[float, float]]:
  """Points along a rounded rectangle, clockwise from the top-left straight edge."""
  x0, y0, x1, y1 = rect.x, rect.y, rect.x + rect.width, rect.y + rect.height
  r = max(0., min(radius, rect.width / 2, rect.height / 2))
  pts: list[tuple[float, float]] = []

  def line(ax, ay, bx, by, n):
    for i in range(n):
      t = i / n
      pts.append((ax + (bx - ax) * t, ay + (by - ay) * t))

  def arc(cx, cy, a0, n):
    for i in range(n):
      a = math.radians(a0 + 90 * i / n)
      pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

  line(x0 + r, y0, x1 - r, y0, SEGMENTS_STRAIGHT)
  arc(x1 - r, y0 + r, -90, SEGMENTS_CORNER)
  line(x1, y0 + r, x1, y1 - r, SEGMENTS_STRAIGHT // 2)
  arc(x1 - r, y1 - r, 0, SEGMENTS_CORNER)
  line(x1 - r, y1, x0 + r, y1, SEGMENTS_STRAIGHT)
  arc(x0 + r, y1 - r, 90, SEGMENTS_CORNER)
  line(x0, y1 - r, x0, y0 + r, SEGMENTS_STRAIGHT // 2)
  arc(x0 + r, y0 + r, 180, SEGMENTS_CORNER)
  return pts


class LongBorder:
  def __init__(self):
    self._alpha = FirstOrderFilter(0., 0.15, 1 / 60)
    self._color = RAINBOW
    self._e2e = False
    self._standby = False   # DEC in ACC: E2E half drawn faint, ready to take over
    self._cache_key = None
    self._points: list[tuple[float, float]] = []

  def update(self) -> None:
    show = False
    try:
      sm = ui_state.sm
      if ui_state.has_longitudinal_control:
        if sm['selfdriveState'].enabled:
          show, self._color = True, RAINBOW
          e2e = bool(sm['selfdriveState'].experimentalMode)
          standby = False
          try:
            dec = sm['longitudinalPlanSP'].dec
            if e2e and dec.active and str(dec.state) != "blended":
              e2e, standby = False, True
          except Exception:
            pass
          self._e2e = e2e
          self._standby = standby
      elif sm['carState'].cruiseState.enabled:
        show, self._color = True, GREEN
    except Exception:
      show = False
    self._alpha.update(1. if show else 0.)

  def render(self, rect: rl.Rectangle) -> None:
    self._sp_label(rect)
    try:
      self._sp_pending_overlay(rect)
    except Exception:
      pass
    a = int(255 * min(max(self._alpha.x, 0.), 1.))
    if a < 5:
      return
    w = BORDER_WIDTH
    outer_radius = CORNER_ROUNDNESS * min(rect.width, rect.height) / 2
    if self._color == RAINBOW:
      self._render_rainbow(rect, outer_radius, a)
      return
    inner = rl.Rectangle(rect.x + w, rect.y + w, rect.width - 2 * w, rect.height - 2 * w)
    roundness = max(0., 2 * (outer_radius - w) / min(inner.width, inner.height))
    # raylib draws the line outward from `inner`, so it ends exactly at the camera view's rounded edge
    rl.draw_rectangle_rounded_lines_ex(inner, roundness, 16, w, rl.Color(*self._color, a))

  def _sp_label(self, rect):
    try:
      if self._alpha.x < 0.05:
        return
      if self._color == RAINBOW:
        if self._standby:
          mode = 'DEC_ACC'
        elif self._e2e:
          mode = 'E2E'
          try:
            if ui_state.sm['longitudinalPlanSP'].dec.active:
              mode = 'DEC_E2E'
          except Exception:
            pass
        else:
          mode = 'CHILL'
      else:
        mode = 'ACC'
      from openpilot.selfdrive.ui.mici.onroad.confidence_ball import sp_badge
      sp_badge(rl.Rectangle(rect.x + rect.width / 2 - 75, rect.y + 24, 150, 50), mode)
    except Exception:
      self._draw_label(rect)

  # ---- SP: settings saved while onroad (pending) / applied after restart ----
  def _sp_pending_overlay(self, rect) -> None:
    import json, os, time
    from openpilot.sunnypilot.system import pending_params as pp
    now = time.monotonic()
    if now - getattr(self, '_sp_pp_check', 0.) > 1.0:
      self._sp_pp_check = now
      self._sp_pp_keys = list(pp.pending_items().keys())
      try:
        ts = os.path.getmtime(pp.PENDING_FILE) if self._sp_pp_keys else 0.
      except Exception:
        ts = 0.
      if ts and ts != getattr(self, '_sp_pp_ts', 0.):
        if getattr(self, '_sp_pp_ts', None) is not None or now > 5:
          self._sp_msg, self._sp_msg_until = "Da luu. Ap dung sau khi tat may & bat lai xe", now + 6.
      self._sp_pp_ts = ts
      if os.path.exists(pp.APPLIED_FILE):
        try:
          with open(pp.APPLIED_FILE) as f:
            keys = json.load(f).get("keys", [])
          os.remove(pp.APPLIED_FILE)
          if keys:
            names = ", ".join(pp.display_name(k) for k in keys)
            self._sp_msg, self._sp_msg_until = "Da ap dung: " + names, now + 8.
        except Exception:
          pass
    font = gui_app.font(FontWeight.BOLD)
    if getattr(self, '_sp_pp_keys', None):
      # small hourglass right of the mode badge (badge: centre x, y 24..74, width 150)
      hx, hy = rect.x + rect.width / 2 + 75 + 16, rect.y + 49
      col = rl.Color(255, 200, 0, 255)
      rl.draw_circle(int(hx), int(hy), 16, rl.Color(0, 0, 0, 170))
      rl.draw_triangle(rl.Vector2(hx - 8, hy - 11), rl.Vector2(hx, hy), rl.Vector2(hx + 8, hy - 11), col)
      rl.draw_triangle(rl.Vector2(hx, hy), rl.Vector2(hx - 8, hy + 11), rl.Vector2(hx + 8, hy + 11), col)
      rl.draw_rectangle(int(hx - 9), int(hy - 13), 18, 2, col)
      rl.draw_rectangle(int(hx - 9), int(hy + 11), 18, 2, col)
    if now < getattr(self, '_sp_msg_until', 0.):
      txt, fs = self._sp_msg, 20
      m = rl.measure_text_ex(font, txt, fs, 0)
      while m.x > rect.width - 140 and fs > 12:
        fs -= 1
        m = rl.measure_text_ex(font, txt, fs, 0)
      x, y = rect.x + rect.width / 2 - m.x / 2, rect.y + 82
      rl.draw_rectangle_rounded(rl.Rectangle(x - 10, y - 4, m.x + 20, m.y + 8), 0.4, 8, rl.Color(0, 0, 0, 200))
      rl.draw_text_ex(font, txt, rl.Vector2(x, y), fs, 0, rl.Color(255, 200, 0, 255))

  def _draw_label(self, rect: rl.Rectangle) -> None:
    if self._color == RAINBOW:
      txt = "End to End" if self._e2e else "sunnypilot ACC"
    else:
      txt = "ACC xe"
    font = gui_app.font(FontWeight.MEDIUM)
    size = rl.measure_text_ex(font, txt, 22, 0)
    pos = rl.Vector2(rect.x + rect.width / 2 - size.x / 2, rect.y + 30)
    rl.draw_text_ex(font, txt, pos, 22, 0, rl.Color(255, 255, 255, 230))

  def _render_rainbow(self, rect: rl.Rectangle, outer_radius: float, a: int) -> None:
    w = BORDER_WIDTH
    key = (rect.x, rect.y, rect.width, rect.height)
    if key != self._cache_key:
      # centre line of the border band
      path = rl.Rectangle(rect.x + w / 2, rect.y + w / 2, rect.width - w, rect.height - w)
      self._points = _perimeter(path, outer_radius - w / 2)
      self._cache_key = key
    pts = self._points
    n = len(pts)
    if n < 2:
      return
    offset = (rl.get_time() * RAINBOW_SPEED) % 1.0
    mid_y = rect.y + rect.height / 2
    for i in range(n):
      p0, p1 = pts[i], pts[(i + 1) % n]
      # E2E -> top half only, ACC -> bottom half only
      seg_top = (p0[1] + p1[1]) / 2 < mid_y
      seg_a = a
      if seg_top != self._e2e:
        if not (self._standby and seg_top):
          continue
        seg_a = int(a * 0.3)  # faint top half: DEC may switch to End to End
      r, g, b = colorsys.hsv_to_rgb((i / n - offset) % 1.0, 0.85, 1.0)
      color = rl.Color(int(r * 255), int(g * 255), int(b * 255), seg_a)
      rl.draw_line_ex(rl.Vector2(p0[0], p0[1]), rl.Vector2(p1[0], p1[1]), w, color)
      if seg_a == a:  # translucent joints would overlap into beads
        rl.draw_circle_v(rl.Vector2(p1[0], p1[1]), w / 2, color)  # round joints on the corners
