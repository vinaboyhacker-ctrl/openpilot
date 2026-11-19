# VW Tiguan MK2 – sunnypilot + Carrot: các chỉnh sửa (bản FINAL 2026-11-19)

Xe: VOLKSWAGEN_TIGUAN_MK2 (MQB), lắp comma 4 kiểu gateway (J533), giao diện mici (536×240).
Nhánh gốc: `carrot-base` @ 64a1776. Nhánh này = bản gốc + toàn bộ chỉnh sửa dưới đây.

## Danh sách chỉnh sửa

| Ngày | Tính năng | File |
|---|---|---|
| 12–13/11 | Bóng tin cậy (confidence ball), ô chế độ CHILL/E2E/DEC, âm thanh | `selfdrive/ui/mici/onroad/confidence_ball.py`, `selfdrive/ui/sunnypilot/mici/onroad/long_border.py` (mới), `selfdrive/ui/soundd.py`, `selfdrive/assets/sounds/ting_ting.wav` (mới) |
| 14/11 | Biểu tượng xe phía trước (mét, km/h, màu TTC), đèn `DUNG`/`DUNG?`, số mét dưới xe trước | `selfdrive/ui/sunnypilot/mici/onroad/stop_indicator.py` (mới), `.../hud_renderer.py`, `selfdrive/ui/mici/onroad/model_renderer.py`, `augmented_road_view.py` |
| 14/11 | Chống "Cruise Fault": không onroad-cycle khi đang chạy; param chỉ-đọc-lúc-khởi-động được lưu chờ và áp dụng khi tắt máy | `system/hardware/hardwared.py`, `system/manager/manager.py`, `sunnypilot/system/pending_params.py` (mới), `sunnypilot/sunnylink/athena/sunnylinkd.py`, `selfdrive/ui/.../settings/developer.py`, `system/ui/lib/application.py` |
| 14–16/11 | Giữ SET ~1s = xoay CHILL/E2E/DEC, giữ RES ~1s = đổi ACC xe/sunnypilot; cảnh báo chế độ | `sunnypilot/selfdrive/car/cruise_helpers.py`, `sunnypilot/selfdrive/selfdrived/events.py`, `selfdrive/selfdrived/events.py`, `selfdrive/selfdrived/selfdrived.py`, `cereal/custom.capnp` |
| 14–16/11 | Giữ SET/RES ≥0.8s không engage (opendbc) | `opendbc_repo/opendbc/car/volkswagen/carstate.py` → xem `opendbc_volkswagen_carstate.patch` |
| – | Giới hạn tốc độ (Carrot fix) | `selfdrive/ui/sunnypilot/mici/onroad/speed_limit.py` |
| – | Phát hình qua Comma4-UI-Streamer | `launch_env.sh` (STREAM=1, QUALITY=100, FPS=20) |
| 19/11 | SET/RES nhấn ngắn (<0.5s) khi đang engage: SET −1 km/h, RES +1 km/h (giống VW gốc). Lần đầu: SET = tốc độ xe, RES = tốc độ cũ. `V_CRUISE_INITIAL` = 10 | `selfdrive/car/cruise.py` |
| 19/11 | Tự bật điều khiển ngang (MADS) khi nổ máy nếu ACC main đã bật sẵn (gửi `lkasEnable` 1 lần khi sẵn sàng + số tiến + nhả phanh) | `sunnypilot/mads/mads.py` |

Cài đặt (param) đang dùng: `Mads=1`, `MadsMainCruiseAllowed=1`, `MadsUnifiedEngagementMode=1`,
`CustomAccIncrementsEnabled=1` (ngắn 1 / dài 5), `LongitudinalPersonality=2` (relaxed; 0=aggressive, 1=standard),
`ExperimentalMode=1`, `DynamicExperimentalControl=1`, `AlphaLongitudinalEnabled=1`.

**Không thay đổi** logic lực phanh / ga / đánh lái. Code mới bọc try/except.

## Cài lại từ nhánh này lên comma
```
cd /data/openpilot
git fetch origin <nhanh_final> && git checkout <nhanh_final>
cd opendbc_repo && git apply ../vw_tiguan_mods/opendbc_volkswagen_carstate.patch
# Khởi động lại CHỈ KHI XE TẮT MÁY (cat /data/params/d/IsOnroad = 0)
```

## Kiểm tra (mô phỏng, không gửi gì vào xe)
```
cd /data/openpilot
PYTHONPATH=. /usr/local/venv/bin/python3 vw_tiguan_mods/tests/test_setres.py selfdrive/car/cruise.py
PYTHONPATH=. /usr/local/venv/bin/python3 vw_tiguan_mods/tests/test_mads_start.py sunnypilot/mads/mads.py
```

## Radar (đang nghiên cứu, chỉ đọc log)
`vw_tiguan_mods/radar/` – script phân tích bus CAN / tương quan, `TIEN_DO.txt` (tiến độ).
Kết luận tạm: 0x313–0x315 trên bus 2 nghi là vật thể radar; danh sách đầy đủ có thể nằm trên CAN riêng radar–camera (không thấy ở kiểu lắp gateway).

## Quy tắc an toàn
- Chỉ khởi động lại comma khi xe ĐÃ TẮT MÁY (khởi động lại khi nổ máy → "Cruise Fault: Restart the car").
- Model không đọc màu đèn: không có biểu tượng đèn hoặc `DUNG?` = người lái phải tự phanh.
