#!/usr/bin/env python3
"""
carrot_man: CarrotMan app <-> sunnypilot bridge.

Network protocol (compatible with the CarrotMan Android app used with CarrotPilot):
  * UDP 7705  device -> app   discovery/status broadcast (json)
  * UDP 7706  app -> device   CarrotMan state json (nRoadLimitSpeed, nSdi*, nTBT*, ...)
  * TCP 7712  app -> device   newline separated json ({"rgdata": {...}, ...})
  * HTTP 7713 app -> device   POST /api/navi/<version> json ({"rgdata": {...}, ...})

Publishes `carrotManSP` at 10 Hz, consumed by the sunnypilot longitudinal planner.
"""
import ipaddress
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import openpilot.cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.carrot.carrot_logic import CarrotNaviState, CarrotSettings, normalize_rgdata

BROADCAST_PORT = 7705
CARROT_MAN_PORT = 7706
NAVI_TCP_PORT = 7712
NAVI_HTTP_PORT = 7713
NAVI_HTTP_MAX_BODY = 4 * 1024 * 1024

BROADCAST_INTERVAL = 1.0
BROADCAST_INTERVAL_CONNECTED = 0.5
PARAMS_UPDATE_INTERVAL = 3.0


def _int_param(params: Params, key: str, default: int) -> int:
  try:
    v = params.get(key, return_default=True)
    return default if v is None else int(v)
  except Exception:
    return default


def read_settings(params: Params) -> CarrotSettings:
  return CarrotSettings(
    speed_ctrl_mode=min(3, max(0, _int_param(params, "CarrotNaviSpeedCtrlMode", 2))),
    safety_factor=min(120, max(80, _int_param(params, "CarrotNaviSafetyFactor", 105))) * 0.01,
    decel_rate=min(300, max(50, _int_param(params, "CarrotNaviDecelRate", 120))) * 0.01,
    speed_ctrl_end_s=float(min(20, max(3, _int_param(params, "CarrotNaviSpeedCtrlEnd", 6)))),
    bump_speed=float(min(100, max(10, _int_param(params, "CarrotNaviBumpSpeed", 35)))),
    road_limit_offset=min(100, max(-1, _int_param(params, "CarrotNaviRoadLimitOffset", -1))),
    turn_speed=float(min(100, max(0, _int_param(params, "CarrotNaviTurnSpeed", 0)))),
    is_metric=params.get_bool("IsMetric"),
  )


def get_local_ip() -> str | None:
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
      s.connect(("8.8.8.8", 80))  # no packets are sent for UDP connect
      return s.getsockname()[0]
  except OSError:
    return None


def get_broadcast_address(local_ip: str | None) -> str:
  try:
    import psutil
    for addresses in psutil.net_if_addrs().values():
      for addr in addresses:
        if addr.family == socket.AF_INET and addr.address == local_ip:
          if addr.broadcast:
            return addr.broadcast
          if addr.netmask:
            return str(ipaddress.ip_network(f"{addr.address}/{addr.netmask}", strict=False).broadcast_address)
  except Exception:
    pass
  return "255.255.255.255"


class CarrotMan:
  def __init__(self):
    self.params = Params()
    self.lock = threading.Lock()
    self.state = CarrotNaviState(read_settings(self.params))
    self.remote_addr: tuple | None = None
    self.last_remote_time = 0.0
    self.ip_address = "0.0.0.0"
    self.last_out = None
    self.v_ego = 0.0
    self.v_cruise_kph = 0.0
    self.controls_active = False

  # ------------------------------------------------------------ receivers
  def handle_obj(self, obj, remote_addr=None) -> None:
    if isinstance(obj, (bytes, bytearray)):
      obj = obj.decode("utf-8", "ignore")
    if isinstance(obj, str):
      obj = obj.strip()
      if not obj:
        return
      obj = json.loads(obj)
    if not isinstance(obj, dict):
      return
    data = normalize_rgdata(obj["rgdata"]) if isinstance(obj.get("rgdata"), dict) else obj
    with self.lock:
      self.state.update_json(data)
      if remote_addr is not None:
        self.remote_addr = remote_addr
        self.last_remote_time = time.monotonic()

  def udp_thread(self) -> None:
    while True:
      try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
          sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
          sock.bind(("0.0.0.0", CARROT_MAN_PORT))
          sock.settimeout(10)
          while True:
            try:
              data, addr = sock.recvfrom(8192)
            except TimeoutError:
              continue
            try:
              self.handle_obj(data, addr)
            except Exception as e:
              cloudlog.warning(f"carrot_man: bad udp packet: {e}")
      except Exception:
        cloudlog.exception("carrot_man: udp thread error")
        time.sleep(2)

  def tcp_thread(self) -> None:
    while True:
      try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", NAVI_TCP_PORT))
        server.listen(2)
        while True:
          conn, addr = server.accept()
          threading.Thread(target=self._tcp_client, args=(conn, addr), daemon=True).start()
      except Exception:
        cloudlog.exception("carrot_man: tcp thread error")
        time.sleep(2)

  def _tcp_client(self, conn: socket.socket, addr) -> None:
    try:
      conn.settimeout(30)
      with conn, conn.makefile("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
          try:
            self.handle_obj(line, addr)
          except Exception as e:
            cloudlog.warning(f"carrot_man: bad tcp line: {e}")
    except Exception:
      pass

  def http_thread(self) -> None:
    carrot = self

    class Handler(BaseHTTPRequestHandler):
      def log_message(self, *args):
        pass

      def _reply(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

      def do_GET(self):
        if self.path == "/health":
          self._reply(200, {"ok": True, "service": "carrot_navi_http"})
        else:
          self._reply(404, {"ok": False})

      def do_POST(self):
        if not self.path.startswith("/api/navi/"):
          self._reply(404, {"ok": False})
          return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > NAVI_HTTP_MAX_BODY:
          self._reply(400, {"ok": False, "error": "bad length"})
          return
        try:
          carrot.handle_obj(self.rfile.read(length), (self.client_address[0], BROADCAST_PORT))
          self._reply(200, {"ok": True, "tmap_version": self.path.rsplit("/", 1)[-1]})
        except Exception as e:
          self._reply(400, {"ok": False, "error": str(e)})

    while True:
      try:
        ThreadingHTTPServer(("0.0.0.0", NAVI_HTTP_PORT), Handler).serve_forever()
      except Exception:
        cloudlog.exception("carrot_man: http thread error")
        time.sleep(2)

  # ------------------------------------------------------------ broadcast
  def make_status_message(self, is_onroad: bool) -> bytes:
    out = self.last_out
    msg = {
      "Carrot2": self.params.get("Version") or "sunnypilot",
      "IsOnroad": is_onroad,
      "CarrotRouteActive": False,
      "ip": self.ip_address,
      "port": CARROT_MAN_PORT,
      "navi_debug": 0,
      "navi_http_port": NAVI_HTTP_PORT,
      "log_carrot": "",
      "v_cruise_kph": self.v_cruise_kph if is_onroad else 0,
      "carcruiseSpeed": self.v_cruise_kph if is_onroad else 0,
      "v_ego_kph": int(self.v_ego * 3.6 + 0.5) if is_onroad else 0,
      "tbt_dist": out.dist_to_turn if out else 0,
      "sdi_dist": out.spd_dist if out else 0,
      "active": self.controls_active if is_onroad else False,
      "xState": 0,
      "trafficState": 0,
    }
    return json.dumps(msg).encode()

  def broadcast(self, sock: socket.socket, is_onroad: bool) -> None:
    ip = get_local_ip()
    if ip is None:
      self.ip_address = "0.0.0.0"
      return
    if ip != self.ip_address:
      self.ip_address = ip
      with self.lock:
        self.remote_addr = None
    with self.lock:
      remote = self.remote_addr if time.monotonic() - self.last_remote_time < 10 else None
    target = remote[0] if remote is not None else get_broadcast_address(ip)
    sock.sendto(self.make_status_message(is_onroad), (target, BROADCAST_PORT))

  # ------------------------------------------------------------ main loop
  def run(self) -> None:
    for target in (self.udp_thread, self.tcp_thread, self.http_thread):
      threading.Thread(target=target, daemon=True).start()

    sm = messaging.SubMaster(['carState', 'selfdriveState'])
    pm = messaging.PubMaster(['carrotManSP'])
    bsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    bsock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    rk = Ratekeeper(10, print_delay_threshold=None)
    last_t = time.monotonic()
    next_broadcast = 0.0
    next_params = 0.0

    while True:
      sm.update(0)
      now = time.monotonic()
      dt = min(max(now - last_t, 0.0), 0.5)
      last_t = now

      is_onroad = sm.alive['carState']
      cs = sm['carState']
      self.v_ego = cs.vEgo if is_onroad else 0.0
      self.v_cruise_kph = cs.vCruiseCluster if is_onroad else 0.0
      self.controls_active = sm['selfdriveState'].active if sm.alive['selfdriveState'] else False
      gas = bool(cs.gasPressed) if is_onroad else False
      brake = bool(cs.brakePressed) if is_onroad else False

      if now >= next_params:
        next_params = now + PARAMS_UPDATE_INTERVAL
        settings = read_settings(self.params)
        with self.lock:
          self.state.settings = settings

      with self.lock:
        out = self.state.step(self.v_ego, self.v_ego * dt, gas, brake)
      self.last_out = out

      msg = messaging.new_message('carrotManSP')
      msg.valid = True
      c = msg.carrotManSP
      c.active = out.active
      c.connected = out.connected
      c.desiredSpeed = float(out.desired_speed)
      c.desiredSource = out.desired_source
      c.roadLimitSpeed = out.road_limit_speed
      c.spdType = out.spd_type
      c.spdLimit = out.spd_limit
      c.spdDist = out.spd_dist
      c.spdCountDown = out.spd_countdown
      c.turnInfo = out.turn_info
      c.distToTurn = out.dist_to_turn
      c.roadName = out.road_name
      c.tbtText = out.tbt_text
      c.sdiDescr = out.sdi_descr
      c.goPosDist = out.go_pos_dist
      c.goPosTime = out.go_pos_time
      c.latitude = float(out.lat)
      c.longitude = float(out.lon)
      c.heading = float(out.heading)
      c.remote = self.remote_addr[0] if self.remote_addr else ""
      pm.send('carrotManSP', msg)

      if now >= next_broadcast:
        next_broadcast = now + (BROADCAST_INTERVAL_CONNECTED if out.connected else BROADCAST_INTERVAL)
        try:
          self.broadcast(bsock, is_onroad)
        except OSError:
          pass

      rk.keep_time()


def main():
  CarrotMan().run()


if __name__ == "__main__":
  main()
