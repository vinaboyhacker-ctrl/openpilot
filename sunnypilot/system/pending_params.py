"""
SP: deferred ("pending") params.

Some settings are only read when card/controlsd start (CarParams). Changing them while the car is
running, followed by an onroad cycle / card restart, re-runs fingerprinting and ECU disable while the
car is on -> Hyundai reports accFaulted ("Cruise Fault: Restart the car") until the car is turned off.

While onroad, writes to these keys are stored in PENDING_FILE instead of the real param.
manager applies them while offroad (before card starts). UI shows the pending / applied state.
A JSON file is used (not "<Key>_Pending" params) because new param keys need a C++ rebuild.

Backup / restore: /data/backup_ui_20261114/pending/HUONG_DAN.txt
"""
import json
import os
import time

PENDING_FILE = "/data/params_pending.json"
APPLIED_FILE = "/data/params_applied.json"

# keys only read at startup (CarParams / card / controlsd init)
KEYS = {
  "AlphaLongitudinalEnabled",
  "OpenpilotEnabledToggle",
  "EnforceTorqueControl",
  "NeuralNetworkLateralControl",
  "TorqueControlTune",
  "IntelligentCruiseButtonManagement",
  "HyundaiLongitudinalTuning",
  "ObdMultiplexingEnabled",
  "SecOCKey",
  "CarPlatformBundle",
}

NAMES = {
  "AlphaLongitudinalEnabled": "ACC sunnypilot / ACC xe",
  "OpenpilotEnabledToggle": "Bat sunnypilot",
  "EnforceTorqueControl": "Torque control",
  "NeuralNetworkLateralControl": "NNLC",
  "TorqueControlTune": "Torque tune",
  "IntelligentCruiseButtonManagement": "ICBM",
  "HyundaiLongitudinalTuning": "Hyundai long tune",
  "CarPlatformBundle": "Chon xe",
}


def _read(path):
  try:
    with open(path) as f:
      return json.load(f)
  except Exception:
    return None


def _write(path, data):
  tmp = path + ".tmp"
  with open(tmp, "w") as f:
    json.dump(data, f)
  os.replace(tmp, path)


def is_onroad(params) -> bool:
  try:
    return bool(params.get_bool("IsOnroad"))
  except Exception:
    return False


def defer(key: str, kind: str, value) -> None:
  """kind: 'bool' (value bool) or 'b64' (value = [b64_string, compression]) for sunnylink."""
  data = _read(PENDING_FILE) or {"items": {}}
  data["items"][key] = {"kind": kind, "value": value}
  data["ts"] = time.time()
  _write(PENDING_FILE, data)


def put_bool_or_defer(params, key: str, value: bool) -> bool:
  """Returns True when deferred (car onroad), False when written immediately."""
  if key in KEYS and is_onroad(params):
    defer(key, "bool", bool(value))
    return True
  params.put_bool(key, value, block=True)
  return False


def set_target_bool(params, key: str, value: bool) -> bool:
  """Onroad: store target (or cancel the pending item if target == current value). Returns True if deferred."""
  if key in KEYS and is_onroad(params):
    if bool(value) == bool(params.get_bool(key)):
      data = _read(PENDING_FILE) or {"items": {}}
      data["items"].pop(key, None)
      if data["items"]:
        data["ts"] = time.time()
        _write(PENDING_FILE, data)
      else:
        try:
          os.remove(PENDING_FILE)
        except Exception:
          pass
    else:
      defer(key, "bool", bool(value))
    return True
  params.put_bool(key, value, block=True)
  return False


def pending_items() -> dict:
  data = _read(PENDING_FILE)
  return (data or {}).get("items", {}) if data else {}


def pending_value(key: str):
  it = pending_items().get(key)
  return it["value"] if it and it.get("kind") == "bool" else None


def apply_pending(params) -> list:
  """Call only while offroad. Copies pending values to the real params, then removes the file."""
  data = _read(PENDING_FILE)
  if not data:
    return []
  applied = []
  for key, it in data.get("items", {}).items():
    try:
      if it["kind"] == "bool":
        params.put_bool(key, bool(it["value"]), block=True)
      elif it["kind"] == "b64":
        from openpilot.sunnypilot.sunnylink.utils import save_param_from_base64_encoded_string
        save_param_from_base64_encoded_string(key, it["value"][0], it["value"][1])
      applied.append(key)
    except Exception:
      pass
  try:
    os.remove(PENDING_FILE)
  except Exception:
    pass
  if applied:
    try:
      _write(APPLIED_FILE, {"keys": applied, "ts": time.time()})
    except Exception:
      pass
  return applied


def display_name(key: str) -> str:
  return NAMES.get(key, key)
