"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import pyray as rl

from openpilot.selfdrive.ui.mici.onroad.hud_renderer import HudRenderer
from openpilot.selfdrive.ui.sunnypilot.onroad.blind_spot_indicators import BlindSpotIndicators
from openpilot.selfdrive.ui.sunnypilot.mici.onroad.speed_limit import SpeedLimitRendererMici
from openpilot.selfdrive.ui.sunnypilot.mici.onroad.stop_indicator import INDICATOR


class HudRendererSP(HudRenderer):
  def __init__(self):
    super().__init__()
    self.blind_spot_indicators = BlindSpotIndicators()
    self.speed_limit_renderer = SpeedLimitRendererMici()
    self.stop_indicator = INDICATOR  # shared: drawn in the side panel by ConfidenceBall

  def _update_state(self) -> None:
    super()._update_state()
    self.blind_spot_indicators.update()
    self.speed_limit_renderer.update()
    try:
      self.stop_indicator.update()
    except Exception:
      pass

  def _render(self, rect: rl.Rectangle) -> None:
    super()._render(rect)
    self.blind_spot_indicators.render(rect)
    try:
      self.stop_indicator.render(rect, not self._can_draw_top_icons)
    except Exception:
      pass
    # speed limit sign (hidden while an alert covers the top of the screen)
    if self._can_draw_top_icons:
      self.speed_limit_renderer.render(rect)

  def _has_blind_spot_detected(self) -> bool:

    return self.blind_spot_indicators.detected
