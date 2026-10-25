"""
Speed limit sign for the comma 4 (mici) onroad HUD.

Reuses the data handling of the comma 3X SpeedLimitRenderer and draws a compact Vienna-style
sign in the top-right corner. Below the sign it shows either the CarrotMan camera (limit + distance)
or the next map speed limit (limit + distance).
"""
import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.speed_limit import SpeedLimitRenderer, SpeedLimitSource, Colors
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Mode as SpeedLimitMode
from openpilot.system.ui.lib.text_measure import measure_text_cached

SIGN_RADIUS = 46
MARGIN = 12
INFO_FONT = 26


class SpeedLimitRendererMici(SpeedLimitRenderer):
  def __init__(self):
    super().__init__()
    self.cam_limit = 0
    self.cam_dist = 0

  def update(self):
    super().update()
    sm = ui_state.sm
    self.cam_limit = 0
    self.cam_dist = 0
    try:
      cn = sm['longitudinalPlanSP'].carrotNavi
      if cn.spdLimit > 0 and cn.spdDist > 0:
        self.cam_limit = int(cn.spdLimit)
        self.cam_dist = int(cn.spdDist)
    except Exception:
      pass

  def _render(self, rect: rl.Rectangle):
    if ui_state.speed_limit_mode == SpeedLimitMode.off and self.cam_limit <= 0:
      return

    center = rl.Vector2(rect.x + rect.width - MARGIN - SIGN_RADIUS, rect.y + MARGIN + SIGN_RADIUS)
    has_limit = self.speed_limit_valid or self.speed_limit_last_valid

    if ui_state.speed_limit_mode != SpeedLimitMode.off:
      self._draw_round_sign(center, has_limit)
      info_y = center.y + SIGN_RADIUS + 6
    else:
      info_y = rect.y + MARGIN

    # Info line under the sign: CarrotMan camera takes priority over the map "ahead" limit
    if self.cam_limit > 0:
      self._draw_info(center.x, info_y, f"CAM {self.cam_limit} • {self._format_dist(self.cam_dist)}", Colors.RED)
    elif self._ahead_valid():
      self._draw_info(center.x, info_y, f"▶ {round(self.speed_limit_ahead)} • {self._format_dist(self.speed_limit_ahead_dist)}",
                      Colors.WHITE)

  def _ahead_valid(self) -> bool:
    return (self.speed_limit_source == SpeedLimitSource.map and self.speed_limit_ahead_valid and
            self.speed_limit_ahead > 0 and self.speed_limit_ahead != self.speed_limit)

  def _draw_round_sign(self, center: rl.Vector2, has_limit: bool):
    warning_enabled = ui_state.speed_limit_mode >= SpeedLimitMode.warning
    is_overspeed = has_limit and round(self.speed_limit_final_last) < round(self.speed)

    txt_color = Colors.BLACK
    if warning_enabled and is_overspeed:
      txt_color = Colors.RED
    elif not self.speed_limit_valid:
      txt_color = Colors.GREY

    # flash the background when over the limit
    bg = Colors.WHITE
    if warning_enabled and is_overspeed and int(rl.get_time() * 2) % 2 == 0:
      bg = rl.Color(255, 220, 220, 255)

    rl.draw_circle_v(rl.Vector2(center.x + 2, center.y + 3), SIGN_RADIUS, rl.Color(0, 0, 0, 120))  # shadow
    rl.draw_circle_v(center, SIGN_RADIUS, bg)
    rl.draw_ring(center, SIGN_RADIUS * 0.78, SIGN_RADIUS, 0, 360, 36, Colors.RED)

    val = str(round(self.speed_limit_last)) if has_limit else "--"
    font_size = 38 if len(val) >= 3 else 46
    self._draw_text_centered(self.font_bold, val, font_size, center, txt_color)

  def _draw_info(self, center_x: float, y: float, text: str, color: rl.Color):
    size = measure_text_cached(self.font_bold, text, INFO_FONT)
    pad = 8
    box = rl.Rectangle(center_x - size.x / 2 - pad, y, size.x + pad * 2, size.y + 4)
    rl.draw_rectangle_rounded(box, 0.5, 8, rl.Color(0, 0, 0, 170))
    rl.draw_text_ex(self.font_bold, text, rl.Vector2(box.x + pad, y + 2), INFO_FONT, 0, color)
