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
  ├─ TTS  wyoming-tag-filter :10210 → kokoro-wyoming (bm_george EN / em_alex ES)
  │         @ KOKORO_SPEED=1.08 — see "Voice / TTS" below
  │         wyoming-piper    :10200  (en_US-amy-low — fallback, unused)
  └─ WX   wu-bridge          :8126  ← GibbonsBluff station (192.168.4.67) pushes
            local WU-format GET every 60s; bridge forwards to ecowitt webhook
```

## Voice / TTS

English Rowan speaks **Kokoro `bm_george`** (British male) at **1.08× speed**; Spanish "Rowan ES" stays `em_alex`. Chosen by A/B audition on the Jabra over bm_lewis (the old voice), other male/female Kokoro voices, and Chatterbox (rejected — needs 4GB+ VRAM we don't have free, and the gain over George didn't justify the LLM/VRAM tradeoff).

- **Speed:** upstream kokoro-wyoming hardcodes `speed=1.0`. We bind-mount a patched `kokoro/main.py` (reads `KOKORO_SPEED` env) and set `KOKORO_SPEED=1.08` in docker-compose. To re-tune: edit the env, `docker compose up -d kokoro-wyoming`. (Language is auto-derived from the voice prefix: `bm_*`→en-gb, `a*`→en-us, `e*`→es.)
- **Pipeline voice** lives in HA `.storage` (not git). Change via `docker exec homeassistant python3 /config/set_rowan_voice.py <token> <voice>` (deploy: `docker cp scripts/set_rowan_voice.py homeassistant:/config/`). Token = `/home/rowan/.ha_token`.
- **Question intonation:** Kokoro under-applies the rising lilt on clipped questions, so `build_rowan_prompt.py` has a REQUIRED rule telling Rowan to phrase questions as full interrogatives ("Is there anything else you need?" not "Anything else?").
- **Pi fillers** (`/home/pi/sounds/fillers/*.wav`, repo `pi-config/sounds/fillers/`) must match the live voice — they're pre-rendered, so re-render in the current voice after any voice change: synth via `scripts/tts_sample.py --voice bm_george`, then `sox <in> -r 22050 -c 1 -b 16 <out>`.
- After any TTS/voice/prompt change, clear cached audio: `sudo rm -f /home/rowan/homeassistant/config/tts/*`.

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

## Reply length cap (num_predict) — added 2026-06-12

`qwen2.5:14b` has `PARAMETER num_predict 100` baked in to cap reply length
(~30s max speech, down from ~50s monologues). HA's Ollama integration only
forwards `num_ctx`, never `num_predict` (entity.py), so a model-level Modelfile
param is the ONLY mechanical output cap — prompt rules alone do not hold this
model to length. Set in place (overwrites the tag, reuses the same blobs):
`printf "FROM qwen2.5:14b\nPARAMETER num_predict 100\n" > /tmp/m && ollama create qwen2.5:14b -f /tmp/m`
(run inside the `ollama` container), then `ollama stop qwen2.5:14b` to force a
reload with the cap. Lives in ollama-data, NOT git.

- **Revert:** original backed up as `qwen2.5-14b-orig` →
  `docker exec ollama ollama cp qwen2.5-14b-orig qwen2.5:14b && docker exec ollama ollama stop qwen2.5:14b`.
- **100 is about the floor.** Trailing control tags (HOST_MESSAGE, GUEST_SUMMARY,
  KB_GAP, LANGUAGE) are emitted at the END of the reply and must fit under the
  cap. Verified they survive at 100 (a 70-word reply + GUEST_SUMMARY just fit);
  tightening further risks clipping them and silently breaking the router/memory.
- **Caps length only, NOT decisiveness.** The model still lists two options and
  ends on "which one sounds better?" — the cap just truncates it. Making Rowan
  pick one / stop asking back is a steerability limit of this 14B; the real fix
  is a more obedient model (Gemma 3 12B / smaller) + RAG, not a tighter cap.

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

## HTTPS access (Tailscale Serve) — added 2026-06-10
Companion app / browser reach HA over HTTPS at **https://rowan.tail49268a.ts.net**
(tailnet-only, auto Let's Encrypt cert via Tailscale; not Funnel/public).

Rebuild if lost:
1. Tailscale admin console → DNS → Enable HTTPS Certificates.
2. `sudo tailscale serve --bg --https=443 http://127.0.0.1:8123`
3. In `homeassistant/config/configuration.yaml` (NOT git-tracked) add:
   ```yaml
   http:
     use_x_forwarded_for: true
     trusted_proxies:
       - 127.0.0.1
       - ::1
   ```
   then `docker restart homeassistant`.
4. Set URLs: `docker cp scripts/set_ha_urls.py homeassistant:/config/ && docker exec homeassistant python /config/set_ha_urls.py` (sets internal/external_url to the https name).
5. Point the companion app server URL at https://rowan.tail49268a.ts.net.
