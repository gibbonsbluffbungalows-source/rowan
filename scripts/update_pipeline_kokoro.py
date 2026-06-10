"""One-shot: point the Rowan Assist pipeline's TTS at Kokoro (bm_lewis).

Runs inside the homeassistant container (aiohttp available):
  docker exec homeassistant python3 /config/update_pipeline_kokoro.py <token> <tts_engine_entity>
"""
import asyncio
import json
import sys

import aiohttp

TOKEN = sys.argv[1]
TTS_ENGINE = sys.argv[2]  # e.g. tts.kokoro
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
            pipelines = resp["result"]["pipelines"]
            rowan = next(p for p in pipelines if p["name"] == "Rowan")

            update = {k: v for k, v in rowan.items() if k != "id"}
            update.update({
                "id": 2,
                "type": "assist_pipeline/pipeline/update",
                "pipeline_id": rowan["id"],
                "tts_engine": TTS_ENGINE,
                "tts_language": "en-us",
                "tts_voice": "bm_lewis",
            })
            await ws.send_json(update)
            resp = await ws.receive_json()
            print(json.dumps(resp, indent=1))


asyncio.run(main())
