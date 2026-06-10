"""Set HA internal/external URL via the websocket API.
Run inside the homeassistant container (has aiohttp). Token mounted at
/config/.self_test_token. One-off; safe to re-run (idempotent)."""
import asyncio, aiohttp, json

URL = "https://rowan.tail49268a.ts.net"
TOKEN = open("/config/.self_test_token").read().strip()


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("http://127.0.0.1:8123/api/websocket") as ws:
            await ws.receive_json()  # auth_required
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            auth = await ws.receive_json()
            assert auth.get("type") == "auth_ok", auth
            await ws.send_json({
                "id": 1, "type": "config/core/update",
                "external_url": URL, "internal_url": URL,
            })
            print(json.dumps(await ws.receive_json()))


asyncio.run(main())
