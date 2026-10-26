"""
Following-distance (driving personality) indicator for the comma 4 onroad HUD.

Shows 1-3 bars (3 = far / relaxed) at the bottom-right. After the steering wheel distance button
changes it, the indicator is highlighted with a label for a few seconds.
"""
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget

# log.LongitudinalPersonality: aggressive = 0, standard = 1, relaxed = 2
BARS = {0: 1, 1: 2, 2: 3}
LABELS = {0: "near", 1: "standard", 2: "far"}
HIGHLIGHT_S = 3.0
BAR_W, BAR_GAP, BAR_H0, BAR_DH = 10, 5, 12, 8
MARGIN = 14
FONT = 26


class PersonalityIndicator(Widget):
  def __init__(self):
    super().__init__()
    self._personality: int | None = None
    self._changed_t = -100.0
    self._font = gui_app.font(FontWeight.BOLD)

  def update(self):
    sm = ui_state.sm
    try:
      p = int(sm['selfdriveState'].personality.raw)
    except Exception:
      return
    if self._personality is not None and p != self._personality:
      self._changed_t = rl.get_time()
    self._personality = p

  def _render(self, rect: rl.Rectangle):
    if self._personality is None or not ui_state.has_longitudinal_control:
      return
    highlight = rl.get_time() - self._changed_t < HIGHLIGHT_S
    n = BARS.get(self._personality, 2)
    alpha = 255 if highlight else 150

    total_w = 3 * BAR_W + 2 * BAR_GAP
    x0 = rect.x + rect.width - MARGIN - total_w
    base_y = rect.y + rect.height - MARGIN
    for i in range(3):
      h = BAR_H0 + i * BAR_DH
      color = rl.Color(255, 255, 255, alpha) if i < n else rl.Color(255, 255, 255, 60)
      rl.draw_rectangle_rounded(rl.Rectangle(x0 + i * (BAR_W + BAR_GAP), base_y - h, BAR_W, h), 0.4, 4, color)

    if highlight:
      text = tr(LABELS.get(self._personality, "standard"))
      size = measure_text_cached(self._font, text, FONT)
      tx = x0 - 10 - size.x
      ty = base_y - size.y
      rl.draw_rectangle_rounded(rl.Rectangle(tx - 8, ty - 2, size.x + 16, size.y + 4), 0.5, 8, rl.Color(0, 0, 0, 170))
      rl.draw_text_ex(self._font, text, rl.Vector2(tx, ty), FONT, 0, rl.WHITE)
