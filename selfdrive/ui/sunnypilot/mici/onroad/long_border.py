"""
Colored frame around the mici camera view that shows who controls speed:
  green - the car's own ACC (stock longitudinal) is engaged
  rainbow - sunnypilot longitudinal control is engaged (colors slowly flow around the frame)
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
    self._cache_key = None
    self._points: list[tuple[float, float]] = []

  def update(self) -> None:
    show = False
    try:
      sm = ui_state.sm
      if ui_state.has_longitudinal_control:
        if sm['selfdriveState'].enabled:
          show, self._color = True, RAINBOW
      elif sm['carState'].cruiseState.enabled:
        show, self._color = True, GREEN
    except Exception:
      show = False
    self._alpha.update(1. if show else 0.)

  def render(self, rect: rl.Rectangle) -> None:
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
    for i in range(n):
      r, g, b = colorsys.hsv_to_rgb((i / n - offset) % 1.0, 0.85, 1.0)
      color = rl.Color(int(r * 255), int(g * 255), int(b * 255), a)
      p0, p1 = pts[i], pts[(i + 1) % n]
      rl.draw_line_ex(rl.Vector2(p0[0], p0[1]), rl.Vector2(p1[0], p1[1]), w, color)
      rl.draw_circle_v(rl.Vector2(p1[0], p1[1]), w / 2, color)  # round joints on the corners
