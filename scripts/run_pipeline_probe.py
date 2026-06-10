"""Run the Rowan Assist pipeline (intent->tts) with a text input, to exercise
the real conversation->TTS path and reveal whether HA streams to TTS.
Run inside the homeassistant container (aiohttp). Token at /config/.self_test_token."""
import asyncio, aiohttp, json, sys

TOKEN = open("/config/.self_test_token").read().strip()
TEXT = sys.argv[1] if len(sys.argv) > 1 else "List a few good coffee shops and breakfast spots nearby."


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("http://127.0.0.1:8123/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            assert (await ws.receive_json()).get("type") == "auth_ok"
            # find the Rowan pipeline id
            await ws.send_json({"id": 1, "type": "assist_pipeline/pipeline/list"})
            pls = (await ws.receive_json())["result"]["pipelines"]
            rowan = next(p for p in pls if p["name"] == "Rowan")
            await ws.send_json({
                "id": 2, "type": "assist_pipeline/run",
                "start_stage": "intent", "end_stage": "tts",
                "input": {"text": TEXT},
                "pipeline": rowan["id"],
                "conversation_id": None,
            })
            # stream events briefly
            end = asyncio.get_event_loop().time() + 20
            while asyncio.get_event_loop().time() < end:
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=20)
                except asyncio.TimeoutError:
                    break
                if msg.get("type") == "event":
                    ev = msg["event"]
                    t = ev.get("type")
                    if t in ("intent-end", "tts-start", "tts-end", "run-end", "error"):
                        data = ev.get("data", {})
                        if t == "intent-end":
                            sp = data.get("intent_output", {}).get("response", {}).get("speech", {}).get("plain", {}).get("speech", "")
                            print("LLM REPLY:", repr(sp[:200]))
                        else:
                            print(t, json.dumps(data)[:160])
                        if t in ("run-end", "error"):
                            break


asyncio.run(main())
