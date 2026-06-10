#!/usr/bin/env python3
"""Point the GibbonsBluff station's "customized upload" at the local wu-bridge.

The AMBWeather WiFi module (Fine Offset hardware) speaks the GW1000-style
binary config protocol on TCP 45000. Its firmware stores but IGNORES the
Ecowitt-type customized upload; only the Wunderground-style GET actually
fires. So: station GETs to wu-bridge :8126 every 60s, which forwards to HA's
ecowitt webhook. Additive — the ambientweather.net upload is untouched.
Re-run any time (idempotent). Disable by setting ACTIVE = 0.

    python3 scripts/setup_station_local_push.py
"""
import socket

STATION = "192.168.4.67"
BRIDGE_SERVER = "192.168.4.114"
BRIDGE_PORT = 8126
STATION_ID = "GIBBONSBLUFF"
STATION_PASSWORD = "localkey"  # checked by wu-bridge
WU_PATH = "/weatherstation/updateweatherstation.php?"  # factory value
ECOWITT_PATH = "/data/report/"  # unused by this firmware; keep factory-ish
INTERVAL_S = 60
TYPE_WUNDERGROUND = 1
ACTIVE = 1

CMD_WRITE_CUSTOMIZED = 0x2B
CMD_READ_CUSTOMIZED = 0x2A
CMD_WRITE_USR_PATH = 0x52
CMD_READ_USR_PATH = 0x51
CMD_REBOOT = 0x40


def packet(cmd: int, payload: bytes = b"") -> bytes:
    size = 3 + len(payload)
    checksum = (cmd + size + sum(payload)) & 0xFF
    return bytes([0xFF, 0xFF, cmd, size]) + payload + bytes([checksum])


def exchange(cmd: int, payload: bytes = b"") -> bytes:
    s = socket.create_connection((STATION, 45000), timeout=5)
    s.sendall(packet(cmd, payload))
    s.settimeout(5)
    data = b""
    try:
        while True:
            chunk = s.recv(1024)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    s.close()
    return data


def lp(text: str) -> bytes:
    raw = text.encode()
    return bytes([len(raw)]) + raw


resp = exchange(CMD_WRITE_USR_PATH, lp(ECOWITT_PATH) + lp(WU_PATH))
print("write usr_path:", resp.hex(), "(00 result = ok)")

payload = (
    lp(STATION_ID) + lp(STATION_PASSWORD)
    + lp(BRIDGE_SERVER)
    + BRIDGE_PORT.to_bytes(2, "big")
    + INTERVAL_S.to_bytes(2, "big")
    + bytes([TYPE_WUNDERGROUND, ACTIVE])
)
resp = exchange(CMD_WRITE_CUSTOMIZED, payload)
print("write customized:", resp.hex(), "(00 result = ok)")
print("readback customized:", exchange(CMD_READ_CUSTOMIZED).hex())

# Reboot so the module picks up the new settings
s = socket.create_connection((STATION, 45000), timeout=5)
s.sendall(packet(CMD_REBOOT))
s.close()
print("station module rebooting (back in ~30s; AWN upload resumes on its own)")
