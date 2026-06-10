#!/usr/bin/env python3
"""Install the Ambient Weather Network config entry for the GibbonsBluff station.

The station isn't shared publicly with coordinates, so the integration's
location-search config flow can't discover it — but its coordinator only
polls the public API by MAC, which works fine. This writes the entry the
flow would have created. Run while Home Assistant is STOPPED:

    docker stop homeassistant
    docker run --rm -v /home/rowan:/home/rowan --entrypoint python3 \
        ghcr.io/home-assistant/home-assistant:stable \
        /home/rowan/scripts/add_gibbonsbluff_entry.py
    docker start homeassistant
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from homeassistant.util import ulid

STORE = Path("/home/rowan/homeassistant/config/.storage/core.config_entries")
MAC = "A4:CF:12:A0:2C:73"

shutil.copy2(STORE, str(STORE) + ".bak")
data = json.loads(STORE.read_text())
entries = data["data"]["entries"]
if any(e["domain"] == "ambient_network" for e in entries):
    print("ambient_network entry already exists; nothing to do")
    raise SystemExit(0)

now = datetime.now(timezone.utc).isoformat()
entries.append({
    "created_at": now,
    "data": {"mac": MAC},
    "disabled_by": None,
    "discovery_keys": {},
    "domain": "ambient_network",
    "entry_id": ulid.ulid_now().upper(),
    "minor_version": 1,
    "modified_at": now,
    "options": {},
    "pref_disable_new_entities": False,
    "pref_disable_polling": False,
    "source": "user",
    "subentries": [],
    "title": "GibbonsBluff",
    "unique_id": MAC,
    "version": 1,
})
STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f"added ambient_network entry for {MAC}")
