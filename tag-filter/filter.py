"""Wyoming TTS proxy that strips Rowan's control tags before speech.

Sits between Home Assistant and kokoro-wyoming. Intercepts `synthesize`
events, removes [GUEST_SUMMARY: ...] and [OPT_OUT: ...] tags from the text,
appends them to /data/tags.log, and fires Home Assistant events
(rowan_guest_summary / rowan_opt_out) so automations can consume them.
Everything else passes through untouched.

Also rewrites the upstream `info` event to disable synthesize streaming,
so tags always arrive in a single synthesize event and can't be split
across chunks.
"""
import asyncio
import json
import logging
import re
import time
import urllib.request
from pathlib import Path

from wyoming.event import async_read_event, async_write_event

LISTEN_HOST, LISTEN_PORT = "0.0.0.0", 10210
UPSTREAM_HOST, UPSTREAM_PORT = "kokoro-wyoming", 10210
HA_URL = "http://host.docker.internal:8123"
TOKEN_FILE = Path("/ha_token")
LOG_FILE = Path("/data/tags.log")

TAG_RE = re.compile(r"\[\s*(GUEST_SUMMARY|OPT_OUT|MORNING_GREETING|LANGUAGE|KB_GAP|HOST_MESSAGE)\s*:\s*([^\]\[]*?)\s*\]", re.I)

EVENT_FOR_TAG = {
    "GUEST_SUMMARY": "rowan_guest_summary",
    "OPT_OUT": "rowan_opt_out",
    "MORNING_GREETING": "rowan_morning_greeting_pref",
    "LANGUAGE": "rowan_language",
    "KB_GAP": "rowan_kb_gap",
    "HOST_MESSAGE": "rowan_host_message",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tag-filter")


def record_tags_blocking(tags: list[tuple[str, str]]) -> None:
    token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else None
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a") as f:
        for name, value in tags:
            f.write(f"{stamp}\t{name.upper()}\t{value}\n")
    if not token:
        log.warning("no HA token mounted; skipping HA events")
        return
    for name, value in tags:
        event_type = EVENT_FOR_TAG.get(name.upper(), "rowan_guest_summary")
        req = urllib.request.Request(
            f"{HA_URL}/api/events/{event_type}",
            data=json.dumps({"value": value}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                log.info("fired %s (%s): HTTP %s", event_type, value, resp.status)
        except Exception as err:
            log.error("failed to fire %s: %s", event_type, err)


def clean_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    tags = TAG_RE.findall(text)
    cleaned = TAG_RE.sub(" ", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or "Okay.", tags


async def filter_event(ev):
    """Strip tags from text-bearing synthesize events; record what was stripped."""
    text = ev.data.get("text") if ev.data else None
    if not text:
        return ev
    cleaned, tags = clean_text(text)
    if tags:
        log.info("stripped %s from %r", [f"{n}:{v}" for n, v in tags], text[:120])
        asyncio.get_running_loop().run_in_executor(None, record_tags_blocking, tags)
        ev.data["text"] = cleaned
    return ev


async def pump_client_to_upstream(reader, up_writer):
    while True:
        ev = await async_read_event(reader)
        if ev is None:
            break
        if ev.type in ("synthesize", "synthesize-chunk"):
            ev = await filter_event(ev)
        await async_write_event(ev, up_writer)


async def pump_upstream_to_client(up_reader, writer):
    while True:
        ev = await async_read_event(up_reader)
        if ev is None:
            break
        if ev.type == "info" and ev.data:
            for tts in ev.data.get("tts", []):
                tts["supports_synthesize_streaming"] = False
        await async_write_event(ev, writer)


async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    try:
        up_reader, up_writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
    except OSError as err:
        log.error("upstream %s:%s unavailable: %s", UPSTREAM_HOST, UPSTREAM_PORT, err)
        writer.close()
        return
    tasks = [
        asyncio.create_task(pump_client_to_upstream(reader, up_writer)),
        asyncio.create_task(pump_upstream_to_client(up_reader, writer)),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, (ConnectionResetError, BrokenPipeError)):
                log.error("pump error from %s: %r", peer, exc)
    finally:
        for w in (writer, up_writer):
            try:
                w.close()
            except Exception:
                pass


async def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    server = await asyncio.start_server(handle_client, LISTEN_HOST, LISTEN_PORT)
    log.info("tag filter listening on %s:%s -> %s:%s", LISTEN_HOST, LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT)
    async with server:
        await server.serve_forever()


asyncio.run(main())
