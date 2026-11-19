"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from cereal import car, custom
from opendbc.car import structs
from openpilot.common.params import Params

ButtonType = car.CarState.ButtonEvent.Type
EventNameSP = custom.OnroadEventSP.EventName

DISTANCE_LONG_PRESS = 50
MODE_LONG_PRESS = 100  # SP: ~1s @ 100Hz cho giu SET / RES

# SP: noi dung thong bao cho experimentalModeSwitched (doc trong events.py)
SWITCH_MSG = ""


class CruiseHelper:
  def __init__(self, CP: structs.CarParams):
    self.CP = CP
    self.params = Params()

    self.button_frame_counts = {ButtonType.gapAdjustCruise: 0}
    self._experimental_mode = False
    self.experimental_mode_switched = False

    # SP: giu SET -> xoay CHILL/E2E/DEC, giu RES -> doi ACC xe / sunnypilot long (lan sau)
    self._sp_hold_counts = {ButtonType.setCruise: 0, ButtonType.resumeCruise: 0}
    self._sp_hold_done = {ButtonType.setCruise: False, ButtonType.resumeCruise: False}

  def update(self, CS, events, experimental_mode) -> None:
    # SP: dem SET/RES ca khi dang dung ACC cua xe (de doi nguoc lai duoc)
    self._sp_update_hold_counts(CS)

    if self.CP.openpilotLongitudinalControl:
      if CS.cruiseState.available:
        self.update_button_frame_counts(CS)

        # toggle experimental mode once on distance button hold
        self.update_experimental_mode(events, experimental_mode)

        self._sp_cycle_long_mode(events)

    self._sp_toggle_alpha_long(events)

  def update_button_frame_counts(self, CS) -> None:
    for button in self.button_frame_counts:
      if self.button_frame_counts[button] > 0:
        self.button_frame_counts[button] += 1

    for button_event in CS.buttonEvents:
      button = button_event.type.raw
      if button in self.button_frame_counts:
        self.button_frame_counts[button] = int(button_event.pressed)

  def update_experimental_mode(self, events, experimental_mode) -> None:
    if self.button_frame_counts[ButtonType.gapAdjustCruise] >= DISTANCE_LONG_PRESS and not self.experimental_mode_switched:
      self._experimental_mode = not experimental_mode
      self.params.put_bool("ExperimentalMode", self._experimental_mode)
      events.add(EventNameSP.experimentalModeSwitched)
      self.experimental_mode_switched = True

  # ---------------- SP: giu nut SET / RES ----------------
  def _sp_update_hold_counts(self, CS) -> None:
    for button in self._sp_hold_counts:
      if self._sp_hold_counts[button] > 0:
        self._sp_hold_counts[button] += 1

    for button_event in CS.buttonEvents:
      button = button_event.type.raw
      if button in self._sp_hold_counts:
        self._sp_hold_counts[button] = int(button_event.pressed)
        if not button_event.pressed:
          self._sp_hold_done[button] = False

  def _sp_hold_triggered(self, button) -> bool:
    if self._sp_hold_counts[button] >= MODE_LONG_PRESS and not self._sp_hold_done[button]:
      self._sp_hold_done[button] = True
      return True
    return False

  def _sp_cycle_long_mode(self, events) -> None:
    global SWITCH_MSG
    if not self._sp_hold_triggered(ButtonType.setCruise):
      return

    em = self.params.get_bool("ExperimentalMode")
    dec = self.params.get_bool("DynamicExperimentalControl")

    if not em:            # CHILL -> E2E
      em, dec, SWITCH_MSG = True, False, "Mode: E2E (Experimental)"
    elif not dec:         # E2E -> DEC
      em, dec, SWITCH_MSG = True, True, "Mode: DEC (Dynamic)"
    else:                 # DEC -> CHILL
      em, dec, SWITCH_MSG = False, False, "Mode: CHILL"

    self.params.put_bool("ExperimentalMode", em)
    self.params.put_bool("DynamicExperimentalControl", dec)
    events.add(EventNameSP.experimentalModeSwitched)

  def _sp_toggle_alpha_long(self, events) -> None:
    global SWITCH_MSG
    if not self._sp_hold_triggered(ButtonType.resumeCruise):
      return
    if not self.CP.alphaLongitudinalAvailable:
      return
    # giong cong tac "alpha longitudinal" trong Developer: khoa khi dang engaged
    mads = getattr(self, 'mads', None)
    if getattr(self, 'enabled', False) or (mads is not None and getattr(mads, 'enabled', False)):
      return

    try:
      from openpilot.sunnypilot.system import pending_params as pp
      cur = pp.pending_value("AlphaLongitudinalEnabled")
      if cur is None:
        cur = self.params.get_bool("AlphaLongitudinalEnabled")
      alpha = not cur
      pp.set_target_bool(self.params, "AlphaLongitudinalEnabled", alpha)
    except Exception:
      alpha = not self.params.get_bool("AlphaLongitudinalEnabled")
      self.params.put_bool("AlphaLongitudinalEnabled", alpha)
    SWITCH_MSG = "Next drive: sunnypilot Long" if alpha else "Next drive: Stock ACC"
    events.add(EventNameSP.experimentalModeSwitched)
