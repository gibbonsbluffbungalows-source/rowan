"""Reset the HA owner account's password via the admin websocket API.
Run inside the homeassistant container. Token at /config/.self_test_token."""
import asyncio, aiohttp, sys

TOKEN = open("/config/.self_test_token").read().strip()
NEWPW = sys.argv[1] if len(sys.argv) > 1 else "bluffrowan2026"


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("http://127.0.0.1:8123/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": TOKEN})
            assert (await ws.receive_json()).get("type") == "auth_ok"
            await ws.send_json({"id": 1, "type": "config/auth/list"})
            users = (await ws.receive_json())["result"]
            owner = next((u for u in users if u.get("is_owner") and u.get("is_active")), None)
            if not owner:
                print("NO OWNER FOUND; users:", [(u.get("name"), u.get("is_owner")) for u in users])
                return
            print("owner:", owner.get("name"), "| id:", owner.get("id"))
            await ws.send_json({
                "id": 2,
                "type": "config/auth_provider/homeassistant/admin_change_password",
                "user_id": owner["id"],
                "password": NEWPW,
            })
            res = await ws.receive_json()
            print("change_password result:", "SUCCESS" if res.get("success") else res)


asyncio.run(main())
