"""One-shot: create the "Rowan ES" Assist pipeline (Spanish twin of "Rowan").

Same whisper container (it honors the per-request language), same Ollama
agent, Kokoro Spanish voice. The satellite's assistant select is flipped
between "Rowan" and "Rowan ES" by the rowan_language automation.

Runs inside the homeassistant container (aiohttp available):
  docker exec homeassistant python3 /config/create_pipeline_es.py <token>
"""
import asyncio
import json
import sys

import aiohttp

TOKEN = sys.argv[1]
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
            if any(p["name"] == "Rowan ES" for p in pipelines):
                print("Rowan ES already exists; nothing to do")
                return
            rowan = next(p for p in pipelines if p["name"] == "Rowan")

            create = {k: v for k, v in rowan.items() if k != "id"}
            create.update({
                "id": 2,
                "type": "assist_pipeline/pipeline/create",
                "name": "Rowan ES",
                "language": "es",
                "conversation_language": "es",
                "stt_language": "es",
                "tts_language": "es",
                "tts_voice": "em_alex",
            })
            await ws.send_json(create)
            resp = await ws.receive_json()
            print(json.dumps(resp, indent=1))


asyncio.run(main())
