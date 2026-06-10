"""Local bridge: GibbonsBluff station -> Home Assistant Ecowitt webhook.

The station's AMBWeather firmware only implements the Wunderground-style
"customized upload" (HTTP GET every 60s). HA's official ecowitt integration
wants Ecowitt-protocol POSTs. This listens for the station's GET, remaps the
fields, and forwards them to the webhook — fully local, no cloud.

Station-side config (written by scripts/setup_station_local_push.py):
customized upload type=wunderground, server=this host, port 8126.
"""
import json
import logging
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = 8126
WEBHOOK_URL = os.environ["ECOWITT_WEBHOOK_URL"]
STATION_PASSWORD = os.environ.get("STATION_PASSWORD", "localkey")
PASSKEY = os.environ.get("PASSKEY", "A4CF12A02C73")

# WU param -> Ecowitt param (unmapped params are dropped)
FIELD_MAP = {
    "tempf": "tempf",
    "humidity": "humidity",
    "indoortempf": "tempinf",
    "indoorhumidity": "humidityin",
    "baromin": "baromrelin",
    "absbaromin": "baromabsin",
    "windspeedmph": "windspeedmph",
    "windgustmph": "windgustmph",
    "winddir": "winddir",
    "rainin": "hourlyrainin",
    "dailyrainin": "dailyrainin",
    "weeklyrainin": "weeklyrainin",
    "monthlyrainin": "monthlyrainin",
    "solarradiation": "solarradiation",
    "UV": "uv",
    "dateutc": "dateutc",
    "softwaretype": "stationtype",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wu-bridge")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if params.get("PASSWORD") != STATION_PASSWORD:
            log.warning("rejected request from %s (bad password)", self.client_address[0])
            self.send_response(403)
            self.end_headers()
            return

        out = {"PASSKEY": PASSKEY, "model": "WS-2902 GibbonsBluff"}
        for wu_key, eco_key in FIELD_MAP.items():
            if wu_key in params:
                out[eco_key] = params[wu_key]

        body = urllib.parse.urlencode(out).encode()
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
        except Exception as err:
            log.error("forward failed: %s", err)
            self.send_response(502)
            self.end_headers()
            return

        log.info(
            "forwarded: temp %s°F hum %s%% wind %s mph -> HTTP %s",
            params.get("tempf"), params.get("humidity"),
            params.get("windspeedmph"), status,
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"success")

    def log_message(self, *args):
        pass  # quiet the default per-request stderr line


ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
