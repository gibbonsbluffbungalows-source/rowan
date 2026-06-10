# Pi wake-word runtime (Hey Rowan / Oye Rowan)

**Why this exists:** the custom `hey_rowan`/`oye_rowan` models were trained for the
ORIGINAL openWakeWord feature frontend. The current `wyoming-openwakeword` 2.x package
uses `pyopen_wakeword`, a reimplementation whose features differ — it loads the models
but scores them ~0.02 (dead). The same models score 0.856 under the original
`openwakeword` package. So we run a tiny custom Wyoming server (`oww_wyoming.py`) on top
of original `openwakeword` + onnxruntime instead of the stock 2.x service.

(Found 2026-06-10. wyoming-openwakeword 1.x would also work but hard-depends on
`tflite-runtime-nightly`, which has no Python 3.13 wheel — hence the custom server.)

## Rebuild on the Pi
```sh
python3 -m venv /home/pi/oww-orig
/home/pi/oww-orig/bin/pip install openwakeword onnxruntime wyoming
# place oww_wyoming.py at /home/pi/oww_wyoming.py
# install wyoming-openwakeword.service (this dir) to /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now wyoming-openwakeword
```
Custom models (`*.onnx` + `*.onnx.data`) live in `/home/pi/wake_models_custom/`
(also in `wake_models_custom/` here). The `.tflite` copies are unused by this runtime.

## Notes
- Live detection scores ~0.64 (vs 0.856 on raw audio) because the satellite's webrtc
  auto-gain/noise-suppression alters the signal. Still well above the 0.5 threshold.
  If misses occur, drop `--threshold` toward 0.4 in the service unit.
- Jabra Mic capture gain MUST stay ~4/7; 7/7 clips speech and kills detection. Pinned by
  `rowan-quiet-hours.sh` (@reboot + hourly).
- `oye_rowan` (Spanish) still scores ~0 even under the original runtime — needs a clean
  "Oye Rowan" recording to judge, and likely a retrain. `hey_rowan` is solid.
- Built-in fallback: `okay_nabu` works under stock wyoming-openwakeword 2.x
  (units staged on the Pi as `*.service.nabu`, installer `use_nabu.sh`).
