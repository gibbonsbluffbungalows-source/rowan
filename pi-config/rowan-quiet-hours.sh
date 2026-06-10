#!/bin/sh
# Quiet hours for Rowan's Jabra speaker (property time = America/Chicago).
# 9 PM - 8 AM Central: PCM 6 of 11 (~half volume); otherwise full (11).
# Also pins Jabra Mic CAPTURE gain to 4/7 always: 7/7 clips speech and breaks
# wake-word detection (found 2026-06-10). Survives reboot/replug via @reboot+hourly.
# Installed in the pi user's crontab (hourly + @reboot); idempotent.
# Source of truth: /home/rowan/pi-config/ on the server (git).
H=$(TZ=America/Chicago date +%H)
if [ "$H" -ge 21 ] || [ "$H" -lt 8 ]; then
    amixer -c USB sset PCM 6 > /dev/null
else
    amixer -c USB sset PCM 11 > /dev/null
fi
amixer -c USB sset Mic 4 > /dev/null 2>&1
