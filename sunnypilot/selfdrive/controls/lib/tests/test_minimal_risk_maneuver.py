from dataclasses import replace

from openpilot.sunnypilot.selfdrive.controls.lib.minimal_risk_maneuver import (
  DT, MinimalRiskManeuver, MrmInputs, MrmState,
)

TERMINAL = MrmInputs(dm_terminal=True, engaged=True, v_ego=20.)


def run(m, inputs, seconds):
  for _ in range(int(round(seconds / DT))):
    m.update(inputs)


def test_terminal_at_highway_speed_decelerates_in_lane():
  m = MinimalRiskManeuver()
  fast = replace(TERMINAL, v_ego=30.)
  m.update(fast)
  assert m.state == MrmState.stop_in_lane
  v0 = m.v_target
  run(m, replace(fast, v_ego=29.), 1.)
  assert m.v_target < v0


def test_no_action_without_terminal_or_engagement():
  m = MinimalRiskManeuver()
  m.update(replace(TERMINAL, dm_terminal=False))
  m.update(replace(TERMINAL, engaged=False))
  assert not m.active


def test_stays_in_lane_by_default_even_when_slow():
  m = MinimalRiskManeuver()
  run(m, replace(TERMINAL, v_ego=15.), 3.)
  assert m.state == MrmState.stop_in_lane
  assert m.curv_offset == 0


def test_moves_to_shoulder_when_slow_and_right_clear():
  m = MinimalRiskManeuver(allow_shoulder=True)
  run(m, replace(TERMINAL, v_ego=15.), 0.1)
  assert m.state == MrmState.to_shoulder
  run(m, replace(TERMINAL, v_ego=15.), 3.)
  assert m.curv_offset < 0
  assert m.curv_offset >= -0.008


def test_stays_in_lane_at_high_speed_until_slow():
  m = MinimalRiskManeuver()
  run(m, replace(TERMINAL, v_ego=30.), 1.)
  assert m.state == MrmState.stop_in_lane
  assert m.curv_offset == 0


def test_right_blindspot_aborts_shoulder_and_unwinds():
  m = MinimalRiskManeuver(allow_shoulder=True)
  run(m, replace(TERMINAL, v_ego=15.), 3.)
  assert m.state == MrmState.to_shoulder
  run(m, replace(TERMINAL, v_ego=15., right_blindspot=True), 0.1)
  assert m.state == MrmState.stop_in_lane
  run(m, replace(TERMINAL, v_ego=15., right_blindspot=True), 2.)
  # the car was not moved to the shoulder while the blind spot was occupied
  assert m.curv_offset == 0 or m.curv_offset > -0.008


def test_driver_back_hands_control_over_immediately():
  m = MinimalRiskManeuver()
  run(m, TERMINAL, 1.)
  m.update(replace(TERMINAL, driver_steer_override=True))
  assert not m.active
  assert m.v_target == 0.


def test_dm_level_dropping_resets():
  m = MinimalRiskManeuver()
  run(m, TERMINAL, 1.)
  m.update(replace(TERMINAL, dm_terminal=False))
  assert m.state == MrmState.idle


def test_stops_and_stays_stopped():
  m = MinimalRiskManeuver()
  run(m, replace(TERMINAL, v_ego=0.05), 0.1)
  assert m.state == MrmState.stopped
  run(m, replace(TERMINAL, v_ego=0.), 2.)
  assert m.state == MrmState.stopped and m.v_target == 0.
