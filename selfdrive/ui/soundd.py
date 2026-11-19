import math
import numpy as np
import time
import wave


from cereal import car, messaging, custom
from openpilot.common.basedir import BASEDIR
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import Ratekeeper
from openpilot.common.utils import retry
from openpilot.common.swaglog import cloudlog

from openpilot.system import micd
from openpilot.system.hardware import HARDWARE

from openpilot.sunnypilot.selfdrive.ui.quiet_mode import QuietMode

SAMPLE_RATE = 48000
SAMPLE_BUFFER = 4096 # (approx 100ms)
MAX_VOLUME = 1.0
MIN_VOLUME = 0.1
ALERT_RAMP_TIME = 4 # seconds to ramp to max volume for warningImmediate
SELFDRIVE_STATE_TIMEOUT = 5 # 5 seconds
FILTER_DT = 1. / (micd.SAMPLE_RATE / micd.FFT_SAMPLES)

AMBIENT_DB = 24 # DB where MIN_VOLUME is applied
DB_SCALE = 30 # AMBIENT_DB + DB_SCALE is where MAX_VOLUME is applied

VOLUME_BASE = 20
if HARDWARE.get_device_type() == "tizi":
  AMBIENT_DB = 30
  VOLUME_BASE = 10

AudibleAlert = car.CarControl.HUDControl.AudibleAlert
AudibleAlertSP = custom.SelfdriveStateSP.AudibleAlert


sound_list_sp: dict[int, tuple[str, int | None, float]] = {
  # AudibleAlertSP, file name, play count (none for infinite)
  AudibleAlertSP.promptSingleLow: ("prompt_single_low.wav", 1, MAX_VOLUME),
  AudibleAlertSP.promptSingleHigh: ("prompt_single_high.wav", 1, MAX_VOLUME),
}

sound_list: dict[int, tuple[str, int | None, float]] = {
  # AudibleAlert, file name, play count (none for infinite)
  AudibleAlert.engage: ("engage.wav", 1, MAX_VOLUME),
  AudibleAlert.disengage: ("disengage.wav", 1, MAX_VOLUME),
  AudibleAlert.refuse: ("refuse.wav", 1, MAX_VOLUME),

  AudibleAlert.prompt: ("prompt.wav", 1, MAX_VOLUME),
  AudibleAlert.promptRepeat: ("prompt.wav", None, MAX_VOLUME),
  AudibleAlert.promptDistracted: ("prompt_distracted.wav", None, MAX_VOLUME),

  AudibleAlert.warningSoft: ("warning_soft.wav", None, MAX_VOLUME),
  AudibleAlert.warningImmediate: ("warning_immediate.wav", None, MAX_VOLUME),

  **sound_list_sp,
}
if HARDWARE.get_device_type() == "tizi":
  sound_list.update({
    AudibleAlert.engage: ("engage_tizi.wav", 1, MAX_VOLUME),
    AudibleAlert.disengage: ("disengage_tizi.wav", 1, MAX_VOLUME),
  })

# SP: am thanh bao hieu phat chong len, khong ngat canh bao chinh
OVERLAY_SOUNDS = {"ting": "prompt_single_high.wav", "ting_ting": "ting_ting.wav"}
CHIME_BRAKE_ACCEL = -1.0     # m/s^2, bat dau giam toc dang ke
CHIME_BRAKE_REARM = -0.5     # m/s^2, cho phep bao lai khi aTarget tren muc nay
CHIME_DECEL_MIN = -0.3       # m/s^2, doi nguon chi tinh khi dang giam toc
CHIME_BRAKE_COOLDOWN = 5.0   # s
LEAD_GONE_TIME = 1.0         # s, xe truoc phai mat >= 1s moi tinh la xuat hien moi
CARROT_POINT_ACTIVE = (3, 4, 5)  # camera, doan do toc do, go giam toc
CARROT_RESET_TIME = 3.0      # s
LEAD_SOURCES = ("lead0", "lead1", "lead2")


def check_selfdrive_timeout_alert(sm):
  ss_missing = time.monotonic() - sm.recv_time['selfdriveState']

  if ss_missing > SELFDRIVE_STATE_TIMEOUT:
    if (sm['selfdriveState'].enabled or sm['selfdriveStateSP'].mads.enabled) and (ss_missing - SELFDRIVE_STATE_TIMEOUT) < 10:
      return True

  return False


class Soundd(QuietMode):
  def __init__(self):
    super().__init__()

    self.load_sounds()

    self.current_alert = AudibleAlert.none
    self.current_volume = MIN_VOLUME
    self.current_sound_frame = 0

    self.ramp_start_volume = MIN_VOLUME
    self.ramp_start_time = 0.

    self.selfdrive_timeout_alert = False

    self.spl_filter_weighted = FirstOrderFilter(0, 2.5, FILTER_DT, initialized=False)

    # SP: trang thai am thanh bao hieu
    self.overlay: str | None = None
    self.overlay_frame = 0
    self.lead_present = False
    self.lead_last_seen = 0.
    self.brake_armed = True
    self.prev_decel_key: str | None = None
    self.last_brake_chime = 0.
    self.carrot_prev_type: int | None = None
    self.carrot_prev_dist = 0
    self.carrot_last_active = 0.

  def load_sounds(self):
    self.loaded_sounds: dict[int, np.ndarray] = {}

    # Load all sounds
    for sound in sound_list:
      filename, play_count, volume = sound_list[sound]

      with wave.open(BASEDIR + "/selfdrive/assets/sounds/" + filename, 'r') as wavefile:
        assert wavefile.getnchannels() == 1
        assert wavefile.getsampwidth() == 2
        assert wavefile.getframerate() == SAMPLE_RATE

        length = wavefile.getnframes()
        self.loaded_sounds[sound] = np.frombuffer(wavefile.readframes(length), dtype=np.int16).astype(np.float32) / (2**16/2)

    self.overlay_sounds: dict[str, np.ndarray] = {}
    for name, filename in OVERLAY_SOUNDS.items():
      with wave.open(BASEDIR + "/selfdrive/assets/sounds/" + filename, 'r') as wavefile:
        assert wavefile.getnchannels() == 1
        assert wavefile.getsampwidth() == 2
        assert wavefile.getframerate() == SAMPLE_RATE
        length = wavefile.getnframes()
        self.overlay_sounds[name] = np.frombuffer(wavefile.readframes(length), dtype=np.int16).astype(np.float32) / (2**16/2)

  def get_sound_data(self, frames): # get "frames" worth of data from the current alert sound, looping when required

    ret = np.zeros(frames, dtype=np.float32)

    if self.should_play_sound(self.current_alert):
      num_loops = sound_list[self.current_alert][1]
      sound_data = self.loaded_sounds[self.current_alert]
      written_frames = 0

      current_sound_frame = self.current_sound_frame % len(sound_data)
      loops = self.current_sound_frame // len(sound_data)

      while written_frames < frames and (num_loops is None or loops < num_loops):
        available_frames = sound_data.shape[0] - current_sound_frame
        frames_to_write = min(available_frames, frames - written_frames)
        ret[written_frames:written_frames+frames_to_write] = sound_data[current_sound_frame:current_sound_frame+frames_to_write]
        written_frames += frames_to_write
        self.current_sound_frame += frames_to_write

    # SP: tron am thanh bao hieu
    ov = self.overlay
    if ov is not None:
      data = self.overlay_sounds[ov]
      n = min(frames, len(data) - self.overlay_frame)
      if n > 0:
        ret[:n] += data[self.overlay_frame:self.overlay_frame + n]
        self.overlay_frame += n
      if self.overlay_frame >= len(data):
        self.overlay = None
      np.clip(ret, -1., 1., out=ret)

    return ret * self.current_volume

  def callback(self, data_out: np.ndarray, frames: int, time, status) -> None:
    if status:
      cloudlog.warning(f"soundd stream over/underflow: {status}")
    data_out[:frames, 0] = self.get_sound_data(frames)

  def update_alert(self, new_alert):
    current_alert_played_once = self.current_alert == AudibleAlert.none or self.current_sound_frame > len(self.loaded_sounds[self.current_alert])
    if self.current_alert != new_alert and (new_alert != AudibleAlert.none or current_alert_played_once):
      if new_alert == AudibleAlert.warningImmediate:
        self.ramp_start_volume = self.current_volume
        self.ramp_start_time = time.monotonic()
      self.current_alert = new_alert
      self.current_sound_frame = 0

  def get_audible_alert(self, sm):
    if sm.updated['selfdriveState']:
      new_alert = sm['selfdriveState'].alertSound.raw
      self.update_alert(new_alert)
    elif check_selfdrive_timeout_alert(sm):
      self.update_alert(AudibleAlert.warningImmediate)
      self.selfdrive_timeout_alert = True
    elif self.selfdrive_timeout_alert:
      self.update_alert(AudibleAlert.none)
      self.selfdrive_timeout_alert = False

  def play_overlay(self, name: str) -> None:
    if self.enabled:  # QuietMode: tat am thanh bao hieu
      return
    self.overlay_frame = 0
    self.overlay = name

  def update_chimes(self, sm) -> None:
    now = time.monotonic()

    # 1a) xe phia truoc moi xuat hien
    if sm.updated['longitudinalPlan']:
      lp = sm['longitudinalPlan']
      if lp.hasLead:
        if not self.lead_present:
          self.play_overlay("ting")
        self.lead_present = True
        self.lead_last_seen = now
      elif now - self.lead_last_seen > LEAD_GONE_TIME:
        self.lead_present = False

      # 2) openpilot bat dau giam toc dang ke
      sp = sm['longitudinalPlanSP']
      a_target = float(lp.aTarget)
      decel_key = None
      if a_target < CHIME_DECEL_MIN:
        if str(lp.longitudinalPlanSource) in LEAD_SOURCES:
          decel_key = "lead"
        elif str(sp.longitudinalPlanSource) == "carrotNavi":
          decel_key = "turn" if sp.carrotNavi.source == "turn" else "carrot"
      if a_target > CHIME_BRAKE_REARM:
        self.brake_armed = True
      strong = a_target < CHIME_BRAKE_ACCEL and self.brake_armed
      new_src = decel_key is not None and decel_key != self.prev_decel_key
      if sp.carrotNavi.longActive and (strong or new_src) and now - self.last_brake_chime >= CHIME_BRAKE_COOLDOWN:
        self.play_overlay("ting_ting")
        self.last_brake_chime = now
        self.brake_armed = False
      self.prev_decel_key = decel_key

    # 1b) Carrot: gap camera / doan do toc do / go giam toc moi (moi diem 1 lan)
    if sm.updated['carrotManSP']:
      cm = sm['carrotManSP']
      if cm.connected and cm.active in CARROT_POINT_ACTIVE and cm.spdDist > 0:
        new_point = self.carrot_prev_type != cm.spdType or cm.spdDist > self.carrot_prev_dist + 100
        if new_point:
          self.play_overlay("ting")
        self.carrot_prev_type = int(cm.spdType)
        self.carrot_prev_dist = int(cm.spdDist)
        self.carrot_last_active = now
      elif now - self.carrot_last_active > CARROT_RESET_TIME:
        self.carrot_prev_type = None
        self.carrot_prev_dist = 0

  def calculate_volume(self, weighted_db):
    volume = ((weighted_db - AMBIENT_DB) / DB_SCALE) * (MAX_VOLUME - MIN_VOLUME) + MIN_VOLUME
    return math.pow(VOLUME_BASE, (np.clip(volume, MIN_VOLUME, MAX_VOLUME) - 1))

  @retry(attempts=10, delay=3)
  def get_stream(self, sd):
    # reload sounddevice to reinitialize portaudio
    sd._terminate()
    sd._initialize()
    return sd.OutputStream(channels=1, samplerate=SAMPLE_RATE, callback=self.callback, blocksize=SAMPLE_BUFFER)

  def soundd_thread(self):
    # sounddevice must be imported after forking processes
    import sounddevice as sd

    sm = messaging.SubMaster(['selfdriveState', 'selfdriveStateSP', 'soundPressure',
                              'longitudinalPlan', 'longitudinalPlanSP', 'carrotManSP'])

    with self.get_stream(sd) as stream:
      rk = Ratekeeper(20)

      cloudlog.info(f"soundd stream started: {stream.samplerate=} {stream.channels=} {stream.dtype=} {stream.device=}, {stream.blocksize=}")
      while True:
        sm.update(0)

        self.load_param()

        # Always update volume, even when alert is playing
        if sm.updated['soundPressure']:
          self.spl_filter_weighted.update(sm["soundPressure"].soundPressureWeightedDb)
          self.current_volume = self.calculate_volume(float(self.spl_filter_weighted.x))

        self.get_audible_alert(sm)
        try:
          self.update_chimes(sm)
        except Exception:
          cloudlog.exception("soundd: update_chimes failed")

        # Ramp up immediate warning sound over 4s
        if self.current_alert == AudibleAlert.warningImmediate:
          elapsed = time.monotonic() - self.ramp_start_time
          ramp_vol = float(np.interp(elapsed, [0, ALERT_RAMP_TIME], [self.ramp_start_volume, MAX_VOLUME]))
          self.current_volume = max(self.current_volume, ramp_vol)

        rk.keep_time()

        assert stream.active


def main():
  s = Soundd()
  s.soundd_thread()


if __name__ == "__main__":
  main()
