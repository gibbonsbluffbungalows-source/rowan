# Rowan Concierge — Running Configuration

Last verified: 2026-06-09 (all components checked live).

## Architecture

```
Guest speaks "Rowan, ..."
        │
  Raspberry Pi 5 (rowan-pi, Tailscale 100.87.194.126)
  ├─ wyoming-openwakeword.service  tcp://127.0.0.1:10400
  │    custom models: /home/pi/wake_models_custom/{hey_rowan,oye_rowan}
  └─ wyoming-satellite.service     tcp://0.0.0.0:10700
       mic/snd: Jabra SPEAK 410 (plughw:CARD=USB,DEV=0)
        │  Wyoming over Tailscale TCP
        ▼
  Server (rowan, Tailscale 100.110.169.17, RTX 5060 Ti)
  Home Assistant (host network, :8123) — Assist pipeline "Rowan"
  ├─ STT  wyoming-whisper   :10300  (faster-whisper medium, beam 1, en)
  ├─ LLM  ollama            :11434  (qwen2.5:14b, GPU, keep_alive=-1)
  └─ TTS  kokoro-wyoming    :10210  (voice: bm_lewis)
          wyoming-piper     :10200  (en_US-amy-low — fallback, unused)
```

## Server (`/home/rowan`)

- `docker-compose.yml` — all five containers. `docker compose up -d` to start.
- HA config volume: `./homeassistant/config` (pipelines/integrations live in `.storage/`, managed via UI/API — not in git).
- HA admin token: `.ha_token` (chmod 600, NOT in git). Rotate once setup is stable.
- Conversation agent: `conversation.rowan` (Ollama integration subentry — system prompt lives there; edit via HA UI → Ollama → Rowan, or `.storage/core.config_entries`).
- Assist pipeline "Rowan": STT `stt.faster_whisper` (en) → `conversation.rowan` → TTS `tts.kokoro` voice `bm_lewis`. Wake word is local on the Pi (pipeline wake_word_entity=null by design).
- `homeassistant/config/update_pipeline_kokoro.py` — example of editing pipelines over the websocket API from inside the HA container.

## Pi (`pi@100.87.194.126`)

- Unit files: `/etc/systemd/system/wyoming-{satellite,openwakeword}.service` (copies tracked here in `pi-configs/`).
- Venvs: `/home/pi/wyoming-satellite`, `/home/pi/wyoming-openwakeword` (satellite installed with `[webrtc]` extra for auto-gain/noise-suppression).
- Mic tuning is controlled from HA (satellite entities): noise suppression = medium, auto gain = 10. HA overrides the CLI flags on connect.
- `pi` user has NO passwordless sudo for these units — unit changes need Mark's password.

## Known quirks

- SSH to the Pi occasionally refuses rapid repeated connections — short delay + retry.
- The wake models are named `hey_rowan`/`oye_rowan` but the spoken trigger is "Rowan" (per Mark).
- Whisper STT runs on CPU: measured 6.7s for 11s of audio (medium, beam 1). GPU migration in progress — see git log.

## Debugging a failed voice interaction

1. Pi side: `ssh pi@100.87.194.126 "journalctl -u wyoming-satellite -u wyoming-openwakeword -f"`
2. HA side: `docker logs homeassistant -f`, or HA UI → Settings → Voice assistants → Rowan → Debug (shows each pipeline stage with timings).
3. Component logs: `docker logs wyoming-whisper|kokoro-wyoming|ollama -f`
4. Text-only LLM test (bypasses audio):
   `curl -s -X POST -H "Authorization: Bearer $(cat /home/rowan/.ha_token)" -H "Content-Type: application/json" -d '{"text":"What time is checkout?","agent_id":"conversation.rowan"}' http://127.0.0.1:8123/api/conversation/process`

## Open items

- [ ] System prompt [TODO]s: WiFi network name, Mark's phone, nearest hospital.
- [ ] Knowledge base: server only has v4; v15 is on Mark's desktop. Needed for Phase 2.
- [ ] Spanish: STT pipeline and Kokoro voice are English-only; "Oye Rowan" wakes but Spanish speech will mistranscribe. Phase 2.
- [ ] Rotate `.ha_token` after launch.
