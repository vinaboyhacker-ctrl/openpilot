"""
Colored frame around the mici camera view that shows who controls speed:
  green - the car's own ACC (stock longitudinal) is engaged
  blue  - sunnypilot longitudinal control is engaged
  none  - nothing is controlling speed
"""
import pyray as rl

from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.selfdrive.ui.ui_state import ui_state

BORDER_WIDTH = 6
CORNER_ROUNDNESS = 0.2 * 1.02   # matches the fake rounded border in augmented_road_view
GREEN = (40, 200, 90)
BLUE = (40, 140, 255)            # Tesla-style path blue


class LongBorder:
  def __init__(self):
    self._alpha = FirstOrderFilter(0., 0.15, 1 / 60)
    self._color = BLUE

  def update(self) -> None:
    show = False
    try:
      sm = ui_state.sm
      if ui_state.has_longitudinal_control:
        if sm['selfdriveState'].enabled:
          show, self._color = True, BLUE
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
    inner = rl.Rectangle(rect.x + w, rect.y + w, rect.width - 2 * w, rect.height - 2 * w)
    outer_radius = CORNER_ROUNDNESS * min(rect.width, rect.height) / 2
    roundness = max(0., 2 * (outer_radius - w) / min(inner.width, inner.height))
    # raylib draws the line outward from `inner`, so it ends exactly at the camera view's rounded edge
    rl.draw_rectangle_rounded_lines_ex(inner, roundness, 16, w, rl.Color(*self._color, a))
