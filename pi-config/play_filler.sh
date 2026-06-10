#!/bin/bash
# Played the instant the guest stops speaking (wired via --stt-stop-command),
# while the server runs STT -> LLM -> TTS (~5s warm). Picks a random short
# acknowledgement in Rowan's own voice (Kokoro bm_lewis) so it never feels
# canned. Purely local on the Pi -> instant, no server round-trip.
DIR=/home/pi/sounds/fillers
f=$(ls "$DIR"/*.wav 2>/dev/null | shuf -n1)
[ -n "$f" ] && aplay -q -D plughw:CARD=USB,DEV=0 "$f"
