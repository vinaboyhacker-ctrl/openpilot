from openpilot.sunnypilot.carrot.carrot_logic import (
  NO_LIMIT_KPH, CarrotNaviState, CarrotSettings, calculate_current_speed, normalize_rgdata,
)

DT = 0.1


def camera_msg(dist, limit=60, sdi_type=1, road_limit=80, **kw):
  msg = {"nRoadLimitSpeed": road_limit, "nSdiType": sdi_type, "nSdiSpeedLimit": limit, "nSdiDist": dist,
         "nSdiBlockType": -1, "nSdiPlusType": -1, "roadcate": 6, "nTBTTurnType": -1, "nTBTDist": 0}
  msg.update(kw)
  return msg


class TestCalculateCurrentSpeed:
  def test_at_target(self):
    assert calculate_current_speed(0, 60, 6, 1.2) == 60

  def test_monotonic_with_distance(self):
    speeds = [calculate_current_speed(d, 60, 6, 1.2) for d in range(0, 2000, 50)]
    assert speeds == sorted(speeds)
    assert speeds[-1] <= NO_LIMIT_KPH


class TestCarrotNaviState:
  def test_disconnected_no_limit(self):
    s = CarrotNaviState()
    out = s.step(20, 2)
    assert not out.connected
    assert out.desired_speed == NO_LIMIT_KPH
    assert out.desired_source == "none"

  def test_camera_slowdown(self):
    s = CarrotNaviState(CarrotSettings(safety_factor=1.0))
    s.update_json(camera_msg(500))
    out = s.step(25, 0)
    assert out.connected and out.active == 3
    assert out.desired_source == "cam"
    assert 60 < out.desired_speed < NO_LIMIT_KPH
    assert out.spd_limit == 60 and out.spd_dist == 500

  def test_camera_distance_counts_down_and_reaches_limit(self):
    s = CarrotNaviState(CarrotSettings(safety_factor=1.0))
    s.update_json(camera_msg(300))
    prev = None
    for _ in range(40):  # 40 * 2.5 m = 100 m
      out = s.step(25, 2.5)
      if prev is not None:
        assert out.desired_speed <= prev + 1e-6
      prev = out.desired_speed
    assert abs(out.spd_dist - 200) <= 1
    # inside the "reach target" window the target equals the camera limit
    s.update_json(camera_msg(50))
    assert s.step(16, 0).desired_speed == 60

  def test_camera_passed_clears(self):
    s = CarrotNaviState()
    s.update_json(camera_msg(20))
    s.step(20, 25)
    out = s.step(20, 1)
    assert out.spd_type == -1
    assert out.desired_speed == NO_LIMIT_KPH

  def test_mobile_camera_mode(self):
    s = CarrotNaviState(CarrotSettings(speed_ctrl_mode=2))
    s.update_json(camera_msg(300, sdi_type=7))
    out = s.step(25, 0)
    assert out.desired_speed == NO_LIMIT_KPH
    assert out.active == 3  # still alerted
    s = CarrotNaviState(CarrotSettings(speed_ctrl_mode=3))
    s.update_json(camera_msg(300, sdi_type=7))
    assert s.step(25, 0).desired_speed < NO_LIMIT_KPH

  def test_mode_off(self):
    s = CarrotNaviState(CarrotSettings(speed_ctrl_mode=0))
    s.update_json(camera_msg(300))
    out = s.step(25, 0)
    assert out.desired_speed == NO_LIMIT_KPH
    assert out.active == 3 and out.spd_dist == 300  # "Alerts Only" still shows the camera

  def test_section_enforcement(self):
    s = CarrotNaviState(CarrotSettings(safety_factor=1.0))
    s.update_json(camera_msg(5000, sdi_type=2, limit=100, nSdiBlockType=2, nSdiBlockDist=3000))
    out = s.step(30, 0)
    assert out.desired_source == "section"
    assert out.desired_speed == 100
    assert out.active == 4

  def test_speed_bump(self):
    s = CarrotNaviState(CarrotSettings(bump_speed=30))
    s.update_json(camera_msg(100, sdi_type=22, limit=0))
    out = s.step(15, 0)
    assert out.desired_source == "bump"
    assert 30 <= out.desired_speed < NO_LIMIT_KPH

  def test_speed_bump_ignored_on_highway(self):
    s = CarrotNaviState()
    s.update_json(camera_msg(100, sdi_type=22, limit=0, roadcate=0))
    out = s.step(20, 0)  # 72 km/h on a road reported as highway
    assert out.desired_speed == NO_LIMIT_KPH
    assert out.active == 5  # alert still shown

  def test_speed_bump_roadcate_kept_when_missing(self):
    s = CarrotNaviState(CarrotSettings(bump_speed=30))
    s.update_json(camera_msg(150, sdi_type=22, limit=0, roadcate=6))
    msg = camera_msg(140, sdi_type=22, limit=0)
    del msg["roadcate"]
    s.update_json(msg)  # a message without roadcate must not turn the road into a highway
    out = s.step(70 / 3.6, 0)
    assert out.desired_source == "bump" and out.desired_speed < NO_LIMIT_KPH

  def test_speed_bump_highway_roadcate_but_slow(self):
    s = CarrotNaviState(CarrotSettings(bump_speed=30))
    s.update_json(camera_msg(100, sdi_type=22, limit=0, roadcate=0))
    assert s.step(40 / 3.6, 0).desired_source == "bump"   # slow already -> still brake for it
    s.update_json(camera_msg(100, sdi_type=22, limit=0, roadcate=0))
    assert s.step(70 / 3.6, 0).desired_speed == NO_LIMIT_KPH  # highway speed on highway -> alert only

  def test_speed_bump_never_from_high_speed(self):
    s = CarrotNaviState(CarrotSettings(bump_speed=30))
    s.update_json(camera_msg(300, sdi_type=22, limit=0, roadcate=6))
    out = s.step(90 / 3.6, 0)
    assert out.desired_speed == NO_LIMIT_KPH and out.active == 5

  def test_speed_bump_alert_only_when_mode_cameras(self):
    s = CarrotNaviState(CarrotSettings(speed_ctrl_mode=1))
    s.update_json(camera_msg(100, sdi_type=22, limit=0))
    out = s.step(15, 0)
    assert out.desired_speed == NO_LIMIT_KPH
    assert out.active == 5 and out.spd_dist == 100

  def test_speed_bump_via_plus_type(self):
    s = CarrotNaviState()
    s.update_json(camera_msg(500, sdi_type=-1, limit=0, nSdiPlusType=22, nSdiPlusDist=80))
    out = s.step(15, 0)
    assert out.active == 5 and out.spd_dist == 80 and out.desired_source == "bump"

  def test_road_limit_offset(self):
    s = CarrotNaviState(CarrotSettings(road_limit_offset=10))
    s.update_json(camera_msg(0, sdi_type=-1, limit=0, road_limit=80))
    out = s.step(20, 0)
    assert out.desired_source == "road"
    assert out.desired_speed == 90
    s.settings.road_limit_offset = -1
    assert s.step(20, 0).desired_speed == NO_LIMIT_KPH

  def test_gas_does_not_override_camera(self):
    s = CarrotNaviState(CarrotSettings(safety_factor=1.0))
    s.update_json(camera_msg(100))
    s.step(25, 0, gas_pressed=False)
    out = s.step(25, 0, gas_pressed=True)
    assert out.desired_source == "cam"

  def test_gas_overrides_road_limit(self):
    s = CarrotNaviState(CarrotSettings(road_limit_offset=0))
    s.update_json(camera_msg(0, sdi_type=-1, limit=0, road_limit=50))
    s.step(20, 0)
    out = s.step(20, 0, gas_pressed=True)  # 72 km/h > 50
    assert out.desired_source == "gas"
    assert out.desired_speed == 72

  def test_turn_speed(self):
    s = CarrotNaviState(CarrotSettings(turn_speed=20))
    s.update_json(camera_msg(0, sdi_type=-1, limit=0, nTBTTurnType=12, nTBTDist=60))
    out = s.step(15, 0)
    assert out.desired_source == "turn"
    assert 20 <= out.desired_speed < NO_LIMIT_KPH

  def test_timeout(self):
    s = CarrotNaviState()
    s.update_json(camera_msg(5000))
    for _ in range(100):
      out = s.step(0, 0)
    assert not out.connected
    assert out.desired_speed == NO_LIMIT_KPH

  def test_road_limit_debounce(self):
    s = CarrotNaviState()
    s.update_json(camera_msg(0, sdi_type=-1, road_limit=80))
    assert s.n_road_limit_speed == 80
    for _ in range(5):
      s.update_json(camera_msg(0, sdi_type=-1, road_limit=50))
    assert s.n_road_limit_speed == 80
    s.update_json(camera_msg(0, sdi_type=-1, road_limit=50))
    assert s.n_road_limit_speed == 50

  def test_bad_values_do_not_crash(self):
    s = CarrotNaviState()
    s.update_json({"nRoadLimitSpeed": "abc", "nSdiType": None, "szPosRoadName": "null"})
    s.update_json("not a dict")  # type: ignore[arg-type]
    s.step(10, 1)


def test_normalize_rgdata():
  data = normalize_rgdata({"nRoadLimitSpeed": 60, "sdi": {"nSdiType": 1, "nSdiDist": 300}, "guidance": {"nTBTDist": 10}})
  assert data["nSdiType"] == 1 and data["nSdiDist"] == 300 and data["nTBTDist"] == 10


class TestBumpApproach:
  def test_gentler_decel_starts_slowing_earlier(self):
    # same bump (25 km/h, 100 m ahead): the gentler profile allows less speed at this distance
    gentle = calculate_current_speed(100, 25, 1.0, 0.9)
    normal = calculate_current_speed(100, 25, 1.0, 1.2)
    assert gentle < normal
    assert gentle < 60
