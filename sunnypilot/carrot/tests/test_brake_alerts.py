from dataclasses import replace

from openpilot.sunnypilot.carrot.brake_alerts import DT, BrakeAlerts, BrakeInputs

CRUISE = BrakeInputs(v_ego=20., a_ego=0., long_active=True)


def run(ba, inputs, seconds):
  chimes, warnings = 0, 0
  for _ in range(int(round(seconds / DT))):
    ba.update(inputs)
    chimes += ba.chime
    warnings += ba.warning
  return chimes, warnings


class TestChime:
  def test_hard_braking_chimes_once(self):
    ba = BrakeAlerts()
    chimes, warnings = run(ba, replace(CRUISE, accel_cmd=-2.5, a_ego=-2.5), 3.)
    assert (chimes, warnings) == (1, 0)

  def test_gentle_braking_is_silent(self):
    ba = BrakeAlerts()
    assert run(ba, replace(CRUISE, accel_cmd=-1.2, a_ego=-1.2), 3.) == (0, 0)

  def test_stopping_accel_at_standstill_is_silent(self):
    ba = BrakeAlerts()
    assert run(ba, replace(CRUISE, v_ego=0.5, accel_cmd=-2.0), 3.) == (0, 0)

  def test_rearms_after_braking_ends(self):
    ba = BrakeAlerts()
    hard = replace(CRUISE, accel_cmd=-2.5, a_ego=-2.5)
    run(ba, hard, 1.)
    run(ba, CRUISE, 3.5)
    assert run(ba, hard, 1.)[0] == 1

  def test_no_chime_without_sunnypilot_long(self):
    ba = BrakeAlerts()
    assert run(ba, replace(CRUISE, long_active=False, accel_cmd=-3., a_ego=-3.), 2.)[0] == 0


class TestWarning:
  def test_lead_closing_without_long_warns(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, long_active=False, has_lead=True, lead_d=40., lead_v=0.)
    assert run(ba, i, .2)[1] > 0

  def test_lead_closing_with_long_handled(self):
    # 20 m/s toward a stopped car 90 m ahead needs ~2.35 m/s^2: sunnypilot brakes for it
    ba = BrakeAlerts()
    i = replace(CRUISE, has_lead=True, lead_d=90., lead_v=0.)
    assert run(ba, i, 1.)[1] == 0

  def test_lead_beyond_long_capability_warns(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, has_lead=True, lead_d=40., lead_v=0.)
    assert run(ba, i, .2)[1] > 0

  def test_driver_braking_silences(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, long_active=False, has_lead=True, lead_d=40., lead_v=0., brake_pressed=True)
    assert run(ba, i, 1.)[1] == 0

  def test_red_light_in_chill_warns_after_delay(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, model_stop=True)
    assert run(ba, i, 1.)[1] == 0
    assert run(ba, i, 1.)[1] > 0

  def test_red_light_in_experimental_handled(self):
    ba = BrakeAlerts()
    assert run(ba, replace(CRUISE, model_stop=True, experimental=True), 3.)[1] == 0

  def test_red_light_while_slowing_is_silent(self):
    ba = BrakeAlerts()
    assert run(ba, replace(CRUISE, model_stop=True, a_ego=-1.0), 3.)[1] == 0

  def test_warning_holds_then_clears(self):
    ba = BrakeAlerts()
    run(ba, replace(CRUISE, long_active=False, has_lead=True, lead_d=40., lead_v=0.), .2)
    assert run(ba, CRUISE, .5)[1] == int(.5 / DT)
    assert run(ba, CRUISE, 1.)[1] < int(1. / DT)
    assert not ba.warning

  def test_warning_suppresses_chime(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, accel_cmd=-2.5, a_ego=-1.0, has_lead=True, lead_d=30., lead_v=0.)
    chimes, warnings = run(ba, i, 1.)
    assert chimes == 0 and warnings > 0


class TestIcon:
  def icon_pulses(self, ba, inputs, seconds):
    chimes, warnings = 0, 0
    for _ in range(int(round(seconds / DT))):
      ba.update(inputs)
      chimes += ba.icon_chime
      warnings += ba.icon_warning
    return chimes, warnings

  def test_icon_without_sunnypilot_braking_warns_once(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, carrot_item=True, carrot_braking=False)
    assert self.icon_pulses(ba, i, 3.) == (0, 1)

  def test_icon_with_sunnypilot_braking_chimes_once(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, carrot_item=True, carrot_braking=True)
    assert self.icon_pulses(ba, i, 3.) == (1, 0)

  def test_icon_sounds_even_when_driver_brakes(self):
    ba = BrakeAlerts()
    i = replace(CRUISE, carrot_item=True, carrot_braking=False, brake_pressed=True)
    assert self.icon_pulses(ba, i, .5) == (0, 1)

  def test_icon_reappearing_sounds_again(self):
    ba = BrakeAlerts()
    shown = replace(CRUISE, carrot_item=True, carrot_braking=False)
    hidden = replace(CRUISE, carrot_item=False)
    assert self.icon_pulses(ba, shown, 1.) == (0, 1)
    assert self.icon_pulses(ba, hidden, 1.) == (0, 0)
    assert self.icon_pulses(ba, shown, 1.) == (0, 1)

  def test_no_icon_no_sound(self):
    ba = BrakeAlerts()
    assert self.icon_pulses(ba, CRUISE, 2.) == (0, 0)

  def test_later_braking_does_not_replay_icon_sound(self):
    # the icon sound is decided when the icon appears; later braking does not replay it
    ba = BrakeAlerts()
    assert self.icon_pulses(ba, replace(CRUISE, carrot_item=True, carrot_braking=False), .5) == (0, 1)
    assert self.icon_pulses(ba, replace(CRUISE, carrot_item=True, carrot_braking=True), 1.) == (0, 0)
