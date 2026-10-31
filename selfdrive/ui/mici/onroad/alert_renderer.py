import time
from enum import StrEnum
from typing import NamedTuple
import pyray as rl
import random
import string
from dataclasses import dataclass
from cereal import messaging, log, car
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.common.filter_simple import BounceFilter, FirstOrderFilter
from openpilot.system.hardware import TICI
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel

from openpilot.selfdrive.ui.sunnypilot.onroad.speed_limit import SpeedLimitAlertRenderer

AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus

ALERT_MARGIN = 18

ALERT_FONT_SMALL = 66 - 50
ALERT_FONT_BIG = 88 - 40

SELFDRIVE_STATE_TIMEOUT = 5  # Seconds
SELFDRIVE_UNRESPONSIVE_TIMEOUT = 10  # Seconds

# Constants
ALERT_COLORS = {
  AlertStatus.normal: rl.Color(0, 0, 0, 255),
  AlertStatus.userPrompt: rl.Color(255, 115, 0, 255),
  AlertStatus.critical: rl.Color(255, 0, 21, 255),
}

TURN_SIGNAL_BLINK_PERIOD = 1 / (80 / 60)  # Mazda heartbeat turn signal BPM

DEBUG = False


class IconSide(StrEnum):
  left = 'left'
  right = 'right'


class IconLayout(NamedTuple):
  texture: rl.Texture
  side: IconSide
  margin_x: int
  margin_y: int
  alpha: float = 255.0


class AlertLayout(NamedTuple):
  text_rect: rl.Rectangle
  icon: IconLayout | None


@dataclass
class Alert:
  text1: str = ""
  text2: str = ""
  size: int = 0
  status: int = 0
  visual_alert: int = car.CarControl.HUDControl.VisualAlert.none
  alert_type: str = ""


# Pre-defined alert instances
ALERT_STARTUP_PENDING = Alert(
  text1="sunnypilot Unavailable",
  text2="Waiting to start",
  size=AlertSize.mid,
  status=AlertStatus.normal,
)

ALERT_CRITICAL_TIMEOUT = Alert(
  text1="TAKE CONTROL IMMEDIATELY",
  text2="System Unresponsive",
  size=AlertSize.full,
  status=AlertStatus.critical,
)

ALERT_CRITICAL_REBOOT = Alert(
  text1="System Unresponsive",
  text2="Reboot Device",
  size=AlertSize.full,
  status=AlertStatus.critical,
)


class AlertRenderer(Widget, SpeedLimitAlertRenderer):
  def __init__(self):
    Widget.__init__(self)
    SpeedLimitAlertRenderer.__init__(self)

    self._alert_text1_label = UnifiedLabel(text="", font_size=ALERT_FONT_BIG, font_weight=FontWeight.DISPLAY, line_height=0.86,
                                           letter_spacing=-0.02)
    self._alert_text2_label = UnifiedLabel(text="", font_size=ALERT_FONT_SMALL, font_weight=FontWeight.ROMAN, line_height=0.86,
                                           letter_spacing=0.025)

    self._prev_alert: Alert | None = None
    self._text_gen_time = 0
    self._alert_text2_gen = ''

    # animation filters
    # TODO: use 0.1 but with proper alert height calculation
    self._alert_y_filter = BounceFilter(0, 0.1, 1 / gui_app.target_fps)
    self._alpha_filter = FirstOrderFilter(0, 0.05, 1 / gui_app.target_fps)

    self._turn_signal_timer = 0.0
    self._turn_signal_alpha_filter = FirstOrderFilter(0.0, 0.3, 1 / gui_app.target_fps)
    self._last_icon_side: IconSide | None = None

    self._load_icons()

  def _load_icons(self):
    self._txt_turn_signal_left = gui_app.texture('icons_mici/onroad/turn_signal_left.png', 104, 96)
    self._txt_turn_signal_right = gui_app.texture('icons_mici/onroad/turn_signal_left.png', 104, 96, flip_x=True)
    self._txt_blind_spot_left = gui_app.texture('icons_mici/onroad/blind_spot_left.png', 134, 150)
    self._txt_blind_spot_right = gui_app.texture('icons_mici/onroad/blind_spot_left.png', 134, 150, flip_x=True)

  def get_alert(self, sm: messaging.SubMaster) -> Alert | None:
    """Generate the current alert based on selfdrive state."""
    ss = sm['selfdriveState']

    # Check if selfdriveState messages have stopped arriving
    if not sm.updated['selfdriveState']:
      recv_frame = sm.recv_frame['selfdriveState']
      time_since_onroad = time.monotonic() - ui_state.started_time

      # 1. Never received selfdriveState since going onroad
      waiting_for_startup = recv_frame < ui_state.started_frame
      if waiting_for_startup and time_since_onroad > 5:
        return ALERT_STARTUP_PENDING

      # 2. Lost communication with selfdriveState after receiving it
      if TICI and not waiting_for_startup:
        ss_missing = time.monotonic() - sm.recv_time['selfdriveState']
        if ss_missing > SELFDRIVE_STATE_TIMEOUT:
          if ss.enabled and (ss_missing - SELFDRIVE_STATE_TIMEOUT) < SELFDRIVE_UNRESPONSIVE_TIMEOUT:
            return ALERT_CRITICAL_TIMEOUT
          return ALERT_CRITICAL_REBOOT

    # No alert if size is none
    if ss.alertSize == 0:
      return None

    # Return current alert
    ret = Alert(text1=ss.alertText1, text2=ss.alertText2, size=ss.alertSize.raw, status=ss.alertStatus.raw,
                visual_alert=ss.alertHudVisual, alert_type=ss.alertType)
    self._prev_alert = ret
    return ret

  def will_render(self) -> tuple[Alert | None, bool]:
    alert = self.get_alert(ui_state.sm)
    return alert or self._prev_alert, alert is None

  def _icon_helper(self, alert: Alert) -> AlertLayout:
    icon_side = None
    txt_icon = None
    icon_alpha = 255.0
    icon_margin_x = 20
    icon_margin_y = 18

    # alert_type format is "EventName/eventType" (e.g., "preLaneChangeLeft/warning")
    event_name = alert.alert_type.split('/')[0] if alert.alert_type else ''

    if event_name == 'preLaneChangeLeft':
      icon_side = IconSide.left
      txt_icon = self._txt_turn_signal_left
      icon_margin_x = 2
      icon_margin_y = 5

    elif event_name == 'preLaneChangeRight':
      icon_side = IconSide.right
      txt_icon = self._txt_turn_signal_right
      icon_margin_x = 2
      icon_margin_y = 5

    elif event_name == 'laneChange':
      icon_side = self._last_icon_side
      txt_icon = self._txt_turn_signal_left if self._last_icon_side == 'left' else self._txt_turn_signal_right
      icon_margin_x = 2
      icon_margin_y = 5

    elif event_name == 'laneChangeBlocked':
      CS = ui_state.sm['carState']
      if CS.leftBlinker:
        icon_side = IconSide.left
      elif CS.rightBlinker:
        icon_side = IconSide.right
      else:
        icon_side = self._last_icon_side
      txt_icon = self._txt_blind_spot_left if icon_side == 'left' else self._txt_blind_spot_right
      icon_margin_x = 8
      icon_margin_y = 0

    elif event_name == 'speedLimitPreActive':
      icon_side, txt_icon, icon_alpha, icon_margin_x, icon_margin_y = SpeedLimitAlertRenderer.speed_limit_pre_active_icon_helper(self)

    else:
      self._turn_signal_timer = 0.0

    self._last_icon_side = icon_side

    # create text rect based on icon presence
    text_x = self._rect.x + ALERT_MARGIN
    text_width = self._rect.width - ALERT_MARGIN
    if icon_side == 'left':
      text_x = self._rect.x + self._txt_turn_signal_right.width
      text_width = self._rect.width - ALERT_MARGIN - self._txt_turn_signal_right.width
    elif icon_side == 'right':
      text_x = self._rect.x + ALERT_MARGIN
      text_width = self._rect.width - ALERT_MARGIN - self._txt_turn_signal_right.width

    text_rect = rl.Rectangle(
      text_x,
      self._alert_y_filter.x,
      text_width,
      self._rect.height,
    )
    icon_layout = IconLayout(txt_icon, icon_side, icon_margin_x, icon_margin_y, icon_alpha) if txt_icon is not None and icon_side is not None else None
    return AlertLayout(text_rect, icon_layout)

  def _render(self, rect: rl.Rectangle) -> bool:
    alert = self.get_alert(ui_state.sm)

    # Animate fade and slide in/out
    self._alert_y_filter.update(self._rect.y - 50 if alert is None else self._rect.y)
    self._alpha_filter.update(0 if alert is None else 1)

    if gui_app.sunnypilot_ui():
      ui_state.onroad_brightness_handle_alerts(ui_state, alert)

    if alert is None:
      # If still animating out, keep the previous alert
      if self._alpha_filter.x > 0.01 and self._prev_alert is not None:
        alert = self._prev_alert
      else:
        self._prev_alert = None
        return False

    self._draw_background(alert)

    # update speed limit UI states
    SpeedLimitAlertRenderer.update(self)

    alert_layout = self._icon_helper(alert)
    self._draw_text(alert, alert_layout)
    self._draw_icons(alert_layout)

    return True

  def _draw_icons(self, alert_layout: AlertLayout) -> None:
    if alert_layout.icon is None:
      return

    if time.monotonic() - self._turn_signal_timer > TURN_SIGNAL_BLINK_PERIOD:
      self._turn_signal_timer = time.monotonic()
      self._turn_signal_alpha_filter.x = 255 * 2
    else:
      self._turn_signal_alpha_filter.update(255 * 0.2)

    if alert_layout.icon.side == 'left':
      pos_x = int(self._rect.x + alert_layout.icon.margin_x)
    else:
      pos_x = int(self._rect.x + self._rect.width - alert_layout.icon.margin_x - alert_layout.icon.texture.width)

    if alert_layout.icon.texture not in (self._txt_turn_signal_left, self._txt_turn_signal_right):
      icon_alpha = alert_layout.icon.alpha
    else:
      icon_alpha = int(min(self._turn_signal_alpha_filter.x, 255))

    rl.draw_texture_ex(alert_layout.icon.texture, rl.Vector2(pos_x, self._rect.y + alert_layout.icon.margin_y), 0.0, 1.0,
                       rl.Color(255, 255, 255, int(icon_alpha * self._alpha_filter.x)))

  def _draw_background(self, alert: Alert) -> None:
    # draw top gradient for alert text at top
    color = ALERT_COLORS.get(alert.status, ALERT_COLORS[AlertStatus.normal])
    color = rl.Color(color.r, color.g, color.b, int(255 * 0.90 * self._alpha_filter.x))
    translucent_color = rl.Color(color.r, color.g, color.b, int(0 * self._alpha_filter.x))

    small_alert_height = round(self._rect.height * 0.583) # 140px at mici height
    medium_alert_height = round(self._rect.height * 0.833) # 200px at mici height

    # alert_type format is "EventName/eventType" (e.g., "preLaneChangeLeft/warning")
    event_name = alert.alert_type.split('/')[0] if alert.alert_type else ''

    # camera / bump / brake icons: no full-screen shade, the camera view stays visible
    if event_name.startswith(('carrotNavi', 'brake')) or event_name == 'carrotIconWarning':
      return

    if event_name == 'preLaneChangeLeft':
      bg_height = small_alert_height
    elif event_name == 'preLaneChangeRight':
      bg_height = small_alert_height
    elif event_name == 'laneChange':
      bg_height = small_alert_height
    elif event_name == 'laneChangeBlocked':
      bg_height = medium_alert_height
    else:
      bg_height = int(self._rect.height)

    solid_height = round(bg_height * 0.2)
    rl.draw_rectangle(int(self._rect.x), int(self._rect.y), int(self._rect.width), solid_height, color)
    rl.draw_rectangle_gradient_v(int(self._rect.x), int(self._rect.y + solid_height), int(self._rect.width),
                                 int(bg_height - solid_height),
                                 color, translucent_color)

  def _draw_carrot_icon(self, source: str, x: float, y: float, size: int) -> None:
    a = int(255 * self._alpha_filter.x)
    if source == "bump":
      # yellow warning triangle with a black hump
      yellow = rl.Color(255, 200, 0, a)
      black = rl.Color(0, 0, 0, a)
      rl.draw_triangle(rl.Vector2(x + size / 2, y), rl.Vector2(x, y + size), rl.Vector2(x + size, y + size), yellow)
      base_y = y + size * 0.80
      hump_h = size * 0.16
      rl.draw_ellipse(int(x + size / 2), int(base_y), size * 0.22, hump_h, black)
      # cover the lower half of the ellipse (stays inside the triangle)
      rl.draw_rectangle(int(x + size * 0.26), int(base_y), int(size * 0.48), int(hump_h + 2), yellow)
      rl.draw_rectangle(int(x + size * 0.16), int(base_y), int(size * 0.68), 4, black)
    else:
      # camera: white body, dark lens; section control gets a bar underneath
      white = rl.Color(255, 255, 255, a)
      dark = rl.Color(40, 40, 40, a)
      body = rl.Rectangle(x + 4, y + size * 0.28, size - 8, size * 0.52)
      rl.draw_rectangle(int(x + size * 0.30), int(y + size * 0.16), int(size * 0.26), int(size * 0.14), white)
      rl.draw_rectangle_rounded(body, 0.3, 8, white)
      cx, cy = int(x + size / 2), int(y + size * 0.54)
      rl.draw_circle(cx, cy, size * 0.19, dark)
      rl.draw_circle(cx, cy, size * 0.08, white)
      if source == "section":
        rl.draw_rectangle(int(x + 4), int(y + size * 0.88), size - 8, 6, rl.Color(255, 70, 70, a))

  def _draw_brake_badge(self, cx: float, cy: float) -> None:
    # red circle with "!" (like a brake warning lamp): sunnypilot will slow down for this item
    a = int(255 * self._alpha_filter.x)
    r = 9
    rl.draw_circle(int(cx), int(cy), r + 2, rl.Color(0, 0, 0, a))
    rl.draw_circle(int(cx), int(cy), r, rl.Color(230, 30, 30, a))
    white = rl.Color(255, 255, 255, a)
    rl.draw_rectangle(int(cx - 1), int(cy - 5), 3, 6, white)
    rl.draw_rectangle(int(cx - 1), int(cy + 2), 3, 3, white)

  def _draw_text(self, alert: Alert, alert_layout: AlertLayout) -> None:
    icon_side = alert_layout.icon.side if alert_layout.icon is not None else None

    # TODO: hack
    alert_text1 = alert.text1.lower().replace('calibrating: ', 'calibrating:\n')
    can_draw_second_line = False
    # TODO: there should be a common way to determine font size based on text length to maximize rect
    if len(alert_text1) <= 12:
      can_draw_second_line = True
      font_size = 92 - 10
    elif len(alert_text1) <= 16:
      can_draw_second_line = True
      font_size = 70
    else:
      font_size = 64 - 10

    if icon_side is not None:
      font_size -= 10

    # CarrotMan camera/bump alerts: icon on the left + numbers only, thinner font
    is_carrot = alert.alert_type.startswith('carrotNavi') if alert.alert_type else False
    if is_carrot:
      font_size = 34  # short numeric text, kept small so it does not hide the road
      icon_size = 40
      icon_x = alert_layout.text_rect.x
      icon_y = alert_layout.text_rect.y + 6
      # icon follows the TMAP item type (not the planner source, which is "none" when only alerting)
      will_brake = False
      try:
        cn = ui_state.sm['longitudinalPlanSP'].carrotNavi
        spd_type = int(cn.spdType)
        source = "bump" if spd_type == 22 else "section" if spd_type == 4 else "cam"
        # sunnypilot is actually slowing down for this item
        will_brake = bool(cn.active) and str(cn.source) == source
      except Exception:
        source = "cam"
      self._draw_carrot_icon(source, icon_x, icon_y, icon_size)
      if will_brake:
        self._draw_brake_badge(icon_x + icon_size - 5, icon_y + icon_size - 5)
      alert_layout = AlertLayout(rl.Rectangle(icon_x + icon_size + 16, alert_layout.text_rect.y,
                                              alert_layout.text_rect.width - icon_size - 10, alert_layout.text_rect.height),
                                 alert_layout.icon)
    self._alert_text1_label.set_font_weight(FontWeight.MEDIUM if is_carrot else FontWeight.DISPLAY)

    color = rl.Color(255, 255, 255, int(255 * 0.9 * self._alpha_filter.x))

    text1_y_offset = 11 if font_size >= 70 else 4
    text_rect1 = rl.Rectangle(
      alert_layout.text_rect.x,
      alert_layout.text_rect.y - text1_y_offset,
      alert_layout.text_rect.width,
      alert_layout.text_rect.height,
    )
    self._alert_text1_label.set_text(alert_text1)
    self._alert_text1_label.set_text_color(color)
    self._alert_text1_label.set_font_size(font_size)
    self._alert_text1_label.set_alignment(rl.GuiTextAlignment.TEXT_ALIGN_LEFT if icon_side != 'left' else rl.GuiTextAlignment.TEXT_ALIGN_RIGHT)
    self._alert_text1_label.render(text_rect1)

    alert_text2 = alert.text2.lower()

    # randomize chars and length for testing
    if DEBUG:
      if time.monotonic() - self._text_gen_time > 0.5:
        self._alert_text2_gen = ''.join(random.choices(string.ascii_lowercase + ' ', k=random.randint(0, 40)))
        self._text_gen_time = time.monotonic()
      alert_text2 = self._alert_text2_gen or alert_text2

    if can_draw_second_line and alert_text2:
      last_line_h = self._alert_text1_label.rect.y + self._alert_text1_label.get_content_height(int(alert_layout.text_rect.width))
      last_line_h -= 4
      if len(alert_text2) > 18:
        small_font_size = 36
      elif len(alert_text2) > 24:
        small_font_size = 32
      else:
        small_font_size = 40
      text_rect2 = rl.Rectangle(
        alert_layout.text_rect.x,
        last_line_h,
        alert_layout.text_rect.width,
        alert_layout.text_rect.height - last_line_h
      )
      color = rl.Color(255, 255, 255, int(255 * 0.65 * self._alpha_filter.x))

      self._alert_text2_label.set_text(alert_text2)
      self._alert_text2_label.set_text_color(color)
      self._alert_text2_label.set_font_size(small_font_size)
      self._alert_text2_label.set_alignment(rl.GuiTextAlignment.TEXT_ALIGN_LEFT if icon_side != 'left' else rl.GuiTextAlignment.TEXT_ALIGN_RIGHT)
      self._alert_text2_label.render(text_rect2)
