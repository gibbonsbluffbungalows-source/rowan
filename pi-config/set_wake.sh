#!/bin/bash
# Audition / set Rowan's wake acknowledgement tone, then say "Hey Rowan" to hear it.
# Usage: set_wake.sh <yeah|imhere|goahead|chime|yes>
name="${1:?usage: set_wake.sh <yeah|imhere|goahead|chime|yes>}"
src="/home/pi/sounds/wake_${name}.wav"
if [ ! -f "$src" ]; then
  echo "no such tone: $src"
  echo "available:"; ls /home/pi/sounds/wake_*.wav | sed 's#.*/wake_##;s#\.wav##' | sed 's/^/  /'
  exit 1
fi
cp "$src" /home/pi/sounds/awake_rowan.wav
sudo -n systemctl restart wyoming-satellite
echo "wake tone -> '$name', satellite restarted. Say 'Hey Rowan' to hear it."
