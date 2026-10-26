"""
Carrot Navi (patched TMAP, protocol v2) receiver for the sunnypilot CarrotMan bridge.

Protocol (see CarrotPilot selfdrive/carrot/carrot_navi_api.md):
  * The device broadcasts {"ip": ...} on UDP 7705 (done by carrot_man's status broadcast).
  * The app opens a control WebSocket on TCP 7714: /api/navi/ws/v2/control/{app_version}
    and sends `requirements_query` with the full 28-item catalog.
  * We answer with a `subscription_manifest` listing all 28 items, enabling only the
    structured JSON items we need (no images, no map video).
  * The app then opens one WebSocket per enabled JSON item and sends `item_update` messages.

Each update is converted to the legacy CarrotMan field names and handed to `on_state(dict)`,
which feeds CarrotNaviState.update_json().
"""
from __future__ import annotations

import asyncio
import json
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from aiohttp import WSMsgType, web

PORT = 7714
PROTOCOL_VERSION = 2
CATALOG_REVISION = 1
MAX_MESSAGE_BYTES = 8 * 1024 * 1024

JSON_NAMES = (
  "vehicle", "guidance_current", "guidance_next", "lane_current",
  "lane_ahead", "speed", "traffic_signal", "crossroad", "route",
  "navigation_status", "app_status", "camera_state", "composition_state",
)
IMAGE_NAMES = (
  "tbt_current_compact", "tbt_current_full", "tbt_next",
  "traffic_signal", "lane_top", "lane_bottom",
  "safety_primary", "safety_secondary", "safety_section",
  "crossroad_minimized", "crossroad_expanded",
  "center_tbt_icon", "center_tbt_text", "center_tbt_fee",
)
RENDER_NAMES = ("map_main",)
CATALOG = tuple([("json", n) for n in JSON_NAMES] + [("image", n) for n in IMAGE_NAMES] +
                [("render", n) for n in RENDER_NAMES])
CATALOG_SET = frozenset(CATALOG)

# Only these structured items are enabled; heartbeat keeps the bridge "connected" while values don't change
ENABLED_JSON = frozenset(("vehicle", "guidance_current", "guidance_next", "lane_current", "speed", "route",
                          "navigation_status"))


def _now_ms() -> int:
  return time.time_ns() // 1_000_000


def _params(kind: str, name: str) -> dict[str, Any]:
  if kind == "json":
    return {"delivery_mode": "on_change_with_heartbeat", "interval_ms": 1000, "stale_timeout_ms": 10000}
  if kind == "image":
    p: dict[str, Any] = {"format": "png", "max_fps": 1, "stale_timeout_ms": 15000}
    if name.startswith("crossroad_"):
      p["theme"] = "auto"  # both crossroad items must resolve to the same theme
    return p
  return {
    "composition": "map_route_vehicle", "width": 320, "height": 240, "dpi": 160, "fps": 1,
    "jpeg_quality": 50, "codec": "jpeg", "h264_bitrate_kbps": 256, "h264_keyframe_interval_sec": 2,
    "camera_mode": "app_sync", "map_theme": "auto", "map_type": "normal", "zoom": 11.0, "tilt": 50.0,
    "bearing": 0.0, "follow_vehicle_bearing": True, "fov": 40.0, "screen_center_y_ratio": 0.8,
    "follow_vehicle": True, "center_latitude": None, "center_longitude": None, "stale_timeout_ms": 5000,
  }


def build_manifest(session_id: str, revision: int = 1) -> dict[str, Any]:
  streams = []
  for handle, (kind, name) in enumerate(CATALOG, start=1):
    streams.append({
      "kind": kind, "name": name, "schema_version": 1, "stream_handle": handle,
      "enabled": kind == "json" and name in ENABLED_JSON,
      "params": _params(kind, name),
    })
  return {
    "type": "subscription_manifest", "protocol_version": PROTOCOL_VERSION, "session_id": session_id,
    "revision": revision, "metrics_enabled": False, "limit_adjustments": [], "streams": streams,
  }


def _num(d: dict | None, key: str, default=None):
  if not isinstance(d, dict):
    return default
  v = d.get(key)
  if isinstance(v, bool) or v is None:
    return default
  try:
    return float(v)
  except (TypeError, ValueError):
    return default


def to_legacy(values: dict[str, Any]) -> dict[str, Any]:
  """Convert the latest v2 structured values to legacy CarrotMan (rgdata) field names."""
  out: dict[str, Any] = {}
  speed = values.get("speed") if isinstance(values.get("speed"), dict) else None
  out["nRoadLimitSpeed"] = int(_num(speed, "road_limit_kph", 0) or 0)

  sdi = speed.get("sdi") if speed else None
  if isinstance(sdi, dict) and _num(sdi, "type") is not None:
    out["nSdiType"] = int(_num(sdi, "type"))
    out["nSdiSpeedLimit"] = int(_num(sdi, "speed_limit_kph", 0))
    out["nSdiDist"] = int(_num(sdi, "distance_m", -1))
    out["nSdiBlockType"] = int(_num(sdi, "block_type", -1))
    out["nSdiBlockSpeed"] = int(_num(sdi, "block_speed_kph", 0))
    out["nSdiBlockDist"] = int(_num(sdi, "block_distance_m", 0))
  else:
    out["nSdiType"] = -1

  sdi2 = speed.get("sdi_secondary") if speed else None
  if isinstance(sdi2, dict) and _num(sdi2, "type") is not None:
    out["nSdiPlusType"] = int(_num(sdi2, "type"))
    out["nSdiPlusSpeedLimit"] = int(_num(sdi2, "speed_limit_kph", 0))
    out["nSdiPlusDist"] = int(_num(sdi2, "distance_m", 0))
  else:
    out["nSdiPlusType"] = -1

  # Average-speed section: treat as "inside section enforcement" when no camera event is closer
  section = speed.get("section") if speed else None
  if isinstance(section, dict) and section.get("active") and _num(section, "speed_limit_kph", 0) > 0:
    if out["nSdiType"] < 0 or out.get("nSdiBlockType", -1) not in (2, 3):
      out["nSdiType"] = 4
      out["nSdiSpeedLimit"] = int(_num(section, "speed_limit_kph"))
      out["nSdiDist"] = int(_num(section, "remaining_distance_m", 0))
      out["nSdiBlockType"] = 2
      out["nSdiBlockDist"] = int(_num(section, "remaining_distance_m", 0))

  lane = values.get("lane_current") if isinstance(values.get("lane_current"), dict) else None
  road_cat = _num(lane, "road_category")
  out["roadcate"] = int(road_cat) if road_cat is not None else 8  # unknown -> treat as a normal road

  for key, prefix in (("guidance_current", ""), ("guidance_next", "Next")):
    g = values.get(key) if isinstance(values.get(key), dict) else None
    if g is not None and _num(g, "turn_type") is not None:
      out[f"nTBTDist{prefix}"] = int(_num(g, "distance_m", 0))
      out[f"nTBTTurnType{prefix}"] = int(_num(g, "turn_type"))
      if not prefix:
        out["szTBTMainText"] = g.get("main_text") or g.get("road_name") or ""
        out["szNearDirName"] = g.get("near_direction") or ""
        out["szFarDirName"] = g.get("far_direction") or ""
    else:
      out[f"nTBTDist{prefix}"] = 0
      out[f"nTBTTurnType{prefix}"] = -1

  route = values.get("route") if isinstance(values.get("route"), dict) else None
  out["nGoPosDist"] = int(_num(route, "remain_distance_m", 0) or 0)
  out["nGoPosTime"] = int(_num(route, "remain_time_sec", 0) or 0)

  vehicle = values.get("vehicle") if isinstance(values.get("vehicle"), dict) else None
  if vehicle is not None and _num(vehicle, "lat") is not None:
    out["vpPosPointLat"] = _num(vehicle, "lat")
    out["vpPosPointLon"] = _num(vehicle, "lon", 0.0)
    out["nPosAngle"] = _num(vehicle, "heading_deg", 0.0)
    out["nPosSpeed"] = _num(vehicle, "speed_kph", 0.0)
    out["szPosRoadName"] = vehicle.get("road_name") or ""
  return out


class CarrotNaviV2Server:
  def __init__(self, on_state: Callable[[dict[str, Any], str], None], log: Callable[[str], None] = print):
    self.on_state = on_state
    self.log = log
    self._lock = threading.Lock()
    self.session_id = ""
    self.revision = 0
    self.control_ws: web.WebSocketResponse | None = None
    self.values: dict[str, Any] = {}
    self.last_update = 0.0

  # ---------------------------------------------------------------- control
  async def ws_control(self, request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=5.0, max_msg_size=MAX_MESSAGE_BYTES, compress=False)
    await ws.prepare(request)
    try:
      async for msg in ws:
        if msg.type != WSMsgType.TEXT:
          continue
        try:
          payload = json.loads(msg.data)
        except ValueError:
          continue
        if not isinstance(payload, dict):
          continue
        mtype = payload.get("type")
        if mtype in ("requirements_query", "catalog_query"):
          if self.control_ws is not None and self.control_ws is not ws and not self.control_ws.closed:
            await ws.send_json({"type": "protocol_error", "protocol_version": PROTOCOL_VERSION, "code": "receiver_busy",
                                "recoverable": True, "message": "another navigation control connection is active"})
            await ws.close(code=1013, message=b"busy")
            break
          if mtype == "requirements_query" and not self._catalog_ok(payload):
            self.log("carrot_navi_v2: app catalog does not match, rejecting")
            await ws.send_json({"type": "protocol_error", "protocol_version": PROTOCOL_VERSION,
                                "code": "invalid_control_message", "recoverable": True,
                                "message": "app v2 catalog does not match receiver catalog"})
            continue
          with self._lock:
            self.session_id = secrets.token_hex(8)
            self.revision += 1
            self.values = {}
            manifest = build_manifest(self.session_id, self.revision)
          self.control_ws = ws
          await ws.send_json(manifest)
          self.log(f"carrot_navi_v2: manifest sent session={self.session_id}")
        elif mtype == "time_sync_request":
          pass
        # manifest_applied / resource_status / stream_status / metrics / protocol_error: nothing to do
    finally:
      if self.control_ws is ws:
        self.control_ws = None
    return ws

  @staticmethod
  def _catalog_ok(req: dict[str, Any]) -> bool:
    if req.get("protocol_version") != PROTOCOL_VERSION or req.get("catalog_revision") != CATALOG_REVISION:
      return False
    streams = req.get("streams")
    if not isinstance(streams, list):
      return False
    offered = [(str(s.get("kind")), str(s.get("name"))) for s in streams if isinstance(s, dict)]
    return len(offered) == len(CATALOG) and set(offered) == CATALOG_SET

  # ---------------------------------------------------------------- items
  async def ws_json(self, request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=10.0, max_msg_size=MAX_MESSAGE_BYTES, compress=False)
    await ws.prepare(request)
    session_id = request.match_info["session_id"]
    name = request.match_info["name"]
    peer = request.remote or ""
    async for msg in ws:
      if msg.type != WSMsgType.TEXT:
        continue
      try:
        payload = json.loads(msg.data)
      except ValueError:
        continue
      if not isinstance(payload, dict) or payload.get("type") != "item_update":
        continue
      with self._lock:
        if session_id != self.session_id or name not in ENABLED_JSON:
          continue
        self.values[name] = payload.get("value") if payload.get("present") else None
        legacy = to_legacy(self.values)
        self.last_update = time.monotonic()
      try:
        self.on_state(legacy, peer)
      except Exception as e:  # never let a bad value kill the socket
        self.log(f"carrot_navi_v2: state update error: {e}")
    return ws

  async def ws_binary(self, request: web.Request) -> web.WebSocketResponse:
    # images / map video are disabled in our manifest; accept and drop anything that arrives
    ws = web.WebSocketResponse(heartbeat=10.0, max_msg_size=MAX_MESSAGE_BYTES, compress=False)
    await ws.prepare(request)
    async for _ in ws:
      pass
    return ws

  async def health(self, request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "carrot_navi_v2", "session": self.session_id,
                              "connected": self.control_ws is not None and not self.control_ws.closed,
                              "items": sorted(k for k, v in self.values.items() if v is not None)})

  # ---------------------------------------------------------------- run
  def make_app(self) -> web.Application:
    app = web.Application(client_max_size=MAX_MESSAGE_BYTES)
    app.router.add_get("/health", self.health)
    app.router.add_get("/api/navi/ws/v2/control/{version}", self.ws_control)
    app.router.add_get("/api/navi/ws/v2/json/{session_id}/{name}", self.ws_json)
    app.router.add_get("/api/navi/ws/v2/image/{session_id}/{name}", self.ws_binary)
    app.router.add_get("/api/navi/ws/v2/render/{session_id}/{name}", self.ws_binary)
    return app

  def run_forever(self, host: str = "0.0.0.0", port: int = PORT) -> None:
    while True:
      loop = asyncio.new_event_loop()
      asyncio.set_event_loop(loop)
      try:
        runner = web.AppRunner(self.make_app(), access_log=None)
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, host, port).start())
        self.log(f"carrot_navi_v2: listening on {port}")
        loop.run_forever()
      except Exception as e:
        self.log(f"carrot_navi_v2: server error: {e}")
        time.sleep(2)
      finally:
        try:
          loop.close()
        except Exception:
          pass
