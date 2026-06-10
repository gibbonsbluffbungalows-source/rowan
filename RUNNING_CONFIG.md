# Rowan Concierge — Running Configuration

Bilingual (EN/ES) voice concierge for Cliffside Bungalow, Pikeville TN.
Last verified: 2026-06-10 (all components checked live).

## Architecture

```
Guest speaks "Rowan, ..." (or "Oye Rowan")
        │
  Raspberry Pi 5 (Tailscale 100.87.194.126, TZ Eastern)
  ├─ wyoming-openwakeword.service  tcp://127.0.0.1:10400
  │    custom models: /home/pi/wake_models_custom/{hey_rowan,oye_rowan}
  ├─ wyoming-satellite.service     tcp://0.0.0.0:10700
  │    mic/snd: Jabra SPEAK 410 (plughw:CARD=USB,DEV=0)
  └─ crontab: rowan-quiet-hours.sh hourly+@reboot (PCM 6/11, 9PM–8AM Central)
        │  Wyoming over Tailscale TCP
        ▼
  Server (rowan, LAN 192.168.4.114, Tailscale 100.110.169.17, RTX 5060 Ti)
  Home Assistant (host network, :8123) — pipelines "Rowan" (EN) / "Rowan ES"
  ├─ STT  wyoming-whisper    :10300  faster-whisper medium GPU, beam 1
  │         (--language en is only the default; each pipeline passes its own)
  ├─ LLM  ollama             :11434  qwen2.5:14b, GPU, keep_alive=-1, num_ctx 16384
  ├─ TTS  wyoming-tag-filter :10210 → kokoro-wyoming (bm_lewis EN / em_alex ES)
  │         wyoming-piper    :10200  (en_US-amy-low — fallback, unused)
  └─ WX   wu-bridge          :8126  ← GibbonsBluff station (192.168.4.67) pushes
            local WU-format GET every 60s; bridge forwards to ecowitt webhook
```

## Control tags (model reply → tag filter → HA event → automation)

| Tag | Event | Effect |
|---|---|---|
| `[GUEST_SUMMARY: …]` | rowan_guest_summary | appended to sensor.rowan_guest_notes (cross-day memory, 15 max, deduped) |
| `[OPT_OUT: pause/resume/silence]` | rowan_opt_out | pause boolean / hard satellite mute |
| `[MORNING_GREETING: yes/no]` | rowan_morning_greeting_pref | flips input_select.rowan_greeting_mode |
| `[LANGUAGE: es/en]` | rowan_language | flips select.rowan_cliffside_assistant (pipeline = ears+voice+prompt cue) |
| `[KB_GAP: question]` | rowan_kb_gap | persistent notification: add this to the KB |

All tags also append to `tag-filter-data/tags.log`.

## System prompt

Built by `scripts/build_rowan_prompt.py` = persona (`prompts/rowan_system_prompt.md`)
+ KB (`Rowan_Knowledge_v15.md`) + FINAL REMINDERS + live Jinja context block
(time, weather brief, guest notes, Spanish flag, greeting state). ~12.6k tokens.
To change: edit source, then
`docker stop homeassistant` →
`docker run --rm -v /home/rowan:/home/rowan --entrypoint python3 ghcr.io/home-assistant/home-assistant:stable /home/rowan/scripts/build_rowan_prompt.py` →
`docker start homeassistant` (writes root-owned `.storage/core.config_entries`).

Hard-won prompt lessons: this 14B needs REQUIRED-strength wording AND a worked
example for behaviors that fight its instincts (tag emission, refusing to guess
item locations).

## Weather (three-level preference in sensor.rowan_weather_brief)

1. **Local push** `sensor.ws_2902_gibbonsbluff_*` — station → wu-bridge → HA
   ecowitt webhook. 60s updates, includes indoor temp, survives internet outage.
   Station-side config: `scripts/setup_station_local_push.py` (GW1000-style
   binary protocol, TCP 45000; additive — AWN cloud upload untouched).
2. **Cloud poll** `sensor.gibbonsbluff_*` — ambient_network integration, by MAC
   (`A4:CF:12:A0:2C:73`), 5-min interval. Entry installed by
   `scripts/add_gibbonsbluff_entry.py` (station has no public coords, so the
   UI config flow can't discover it). No API keys needed or stored.
3. **Met.no** `weather.forecast_cliffside_bungalow` — always supplies sky
   condition + today's forecast (station has no forecast).

Brief refreshes /30min + HA start + `rowan_weather_refresh` event.

## Guest lifecycle

- `input_select.rowan_greeting_mode`: off / **first_wake** (default) / time (8:30 announce) / motion (future Shelly).
- `input_button.rowan_new_guest`: clears notes, unpauses, unmutes, first_wake, EN pipeline.
- Ops automations: model warm-up ~45s after HA start (kills the ~14s first-query
  prefill); satellite-offline persistent notification after 5 min (point at
  notify.mobile_app_* once the companion app is installed).

## Auth & secrets

- `/home/rowan/.ha_token` (600, NOT in git) = LLAT "rowan-services-20260610".
  tag-filter mounts it read-only and reads per event → rotate by overwriting the
  file in place; no container restart. Old token revoked 2026-06-10.

## Debugging a failed voice interaction

1. Pi: `ssh pi@100.87.194.126 "journalctl -u wyoming-satellite -u wyoming-openwakeword -f"` (retry if connection refused)
2. HA: `docker logs homeassistant -f`, or UI → Settings → Voice assistants → Debug (per-stage timings).
3. Components: `docker logs wyoming-whisper|kokoro-wyoming|wyoming-tag-filter|wu-bridge|ollama -f`
4. Text-only LLM test (bypasses audio; does NOT fire tag events — those need TTS):
   `curl -s -X POST -H "Authorization: Bearer $(cat /home/rowan/.ha_token)" -H "Content-Type: application/json" -d '{"text":"What time is checkout?","agent_id":"conversation.rowan"}' http://127.0.0.1:8123/api/conversation/process`
5. Weather chain: `docker logs wu-bridge -f` (one line per station push).

## Open items

- [ ] Live voice test at the Jabra: EN, then "Rowan, habla español", audible announce test.
- [ ] Fill KB from rowan_kb_gap notifications (towels, first aid, hair dryer, iron…).
- [ ] Off-site backup: everything is in this git repo, but it has no remote yet.
- [ ] Booking-calendar auto guest-reset (needs Airbnb/VRBO iCal URL).
- [ ] Shelly Motion: greeting → first-motion-after-8am when installed.
- [ ] HA companion app on Mark's phone → switch watchdog to push notifications.
