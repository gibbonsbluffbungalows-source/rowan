"""Set the English 'Rowan' Assist pipeline's TTS voice (preserves all other fields).

Runs inside the homeassistant container (aiohttp available):
  docker exec homeassistant python3 /config/set_rowan_voice.py <token> <voice>

Only touches the 'Rowan' (English) pipeline; 'Rowan ES' keeps its Spanish voice.
The Kokoro server derives language from the voice prefix, so changing voice is
sufficient (bm_* -> en-gb automatically).
"""
import asyncio
import json
import sys

import aiohttp

TOKEN = sys.argv[1]
VOICE = sys.argv[2]
URL = "ws://127.0.0.1:8123/api/websocket"


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(URL) as ws:
            await ws.receive_json()  # auth_required
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            msg = await ws.receive_json()
            assert msg["type"] == "auth_ok", msg

            await ws.send_json({"id": 1, "type": "assist_pipeline/pipeline/list"})
            resp = await ws.receive_json()
            rowan = next(p for p in resp["result"]["pipelines"] if p["name"] == "Rowan")

            update = {k: v for k, v in rowan.items() if k != "id"}
            update.update({
                "id": 2,
                "type": "assist_pipeline/pipeline/update",
                "pipeline_id": rowan["id"],
                "tts_voice": VOICE,
            })
            await ws.send_json(update)
            resp = await ws.receive_json()
            print(json.dumps(resp, indent=1))


asyncio.run(main())
