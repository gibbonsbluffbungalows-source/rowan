"""Wyoming TTS proxy: strips Rowan's control tags AND adapts Home Assistant's
streaming TTS to this Kokoro build.

Sits between Home Assistant and kokoro-wyoming.

Streaming adapter
-----------------
HA streams an LLM reply as: SynthesizeStart, SynthesizeChunk* (text deltas),
Synthesize(full text, for backwards-compat), SynthesizeStop. This Kokoro build
only understands a single full-text `Synthesize` event, so we advertise streaming
support to HA, buffer the incoming text, and emit ONE full `Synthesize` per
completed SENTENCE to Kokoro as soon as it is ready. That lets audio start ~1.5s
in instead of after the whole reply finishes generating + synthesizing.

Kokoro answers each per-sentence Synthesize with its own (AudioStart, AudioChunk*,
AudioStop) sequence. We reframe those into the single (AudioStart, AudioChunk*,
SynthesizeStopped) stream HA expects: forward the first AudioStart only, forward
every AudioChunk, drop intermediate AudioStarts/AudioStops, and emit one
SynthesizeStopped once HA has finished sending text AND every sentence's audio
has been received.

Tag / markdown handling
-----------------------
[GUEST_SUMMARY: ...] etc. and markdown are stripped per emitted sentence. A flush
is NEVER made past an unclosed '[', so a control tag can't be split across
Synthesize calls. Stripped tags are logged to /data/tags.log and fired as HA
events (rowan_guest_summary / rowan_opt_out / ...).

Non-streaming path
------------------
A bare `Synthesize` with no preceding `SynthesizeStart` (e.g. announce) is handled
the old way: strip tags+markdown, forward a single Synthesize, and pass Kokoro's
audio through unchanged (including AudioStop).

Also rewrites the upstream `info` event to advertise supports_synthesize_streaming.
"""
import asyncio
import json
import logging
import re
import time
import urllib.request
from pathlib import Path

from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import async_read_event, async_write_event
from wyoming.tts import (
    Synthesize,
    SynthesizeChunk,
    SynthesizeStart,
    SynthesizeStop,
    SynthesizeStopped,
)

LISTEN_HOST, LISTEN_PORT = "0.0.0.0", 10210
UPSTREAM_HOST, UPSTREAM_PORT = "kokoro-wyoming", 10210
HA_URL = "http://host.docker.internal:8123"
TOKEN_FILE = Path("/ha_token")
LOG_FILE = Path("/data/tags.log")

TAG_RE = re.compile(r"\[\s*(GUEST_SUMMARY|OPT_OUT|MORNING_GREETING|LANGUAGE|KB_GAP|HOST_MESSAGE)\s*:\s*([^\]\[]*?)\s*\]", re.I)

# Sentence end: .!? (+ optional closing quote/bracket) followed by whitespace.
# Requiring a trailing space avoids splitting "10 a.m." or "8.5" mid-token.
SENT_BOUNDARY = re.compile(r"[.!?]+[\"')\]]*\s")

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


def strip_markdown(text: str) -> str:
    """Remove markdown formatting so TTS doesn't read '**', '#', backticks, etc."""
    # [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # paired emphasis: **bold**, __bold__, *italic*, _italic_  -> inner text
    text = re.sub(r"(\*\*|__|\*|_)(.+?)\1", r"\2", text, flags=re.S)
    # per-line: strip leading headings, list bullets, blockquotes
    lines = []
    for ln in text.split("\n"):
        ln = re.sub(r"^\s{0,3}#{1,6}\s*", "", ln)
        ln = re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", ln)
        ln = re.sub(r"^\s*>\s?", "", ln)
        lines.append(ln)
    text = "\n".join(lines)
    # remove any leftover/unbalanced markup characters (e.g. a stray '**')
    text = re.sub(r"[*_`~#]+", "", text)
    return text


def clean_segment(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Strip control tags + markdown. Returns (cleaned, tags); cleaned may be ''."""
    tags = TAG_RE.findall(text)
    cleaned = TAG_RE.sub(" ", text)
    cleaned = strip_markdown(cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, tags


def clean_text(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Non-streaming clean: like clean_segment but never returns empty text."""
    cleaned, tags = clean_segment(text)
    return cleaned or "Okay.", tags


def next_flush(buf: str) -> tuple[str, str]:
    """Split buf at the last complete sentence boundary, never flushing past an
    unclosed '['. Returns (emit, remaining); emit is '' if nothing is ready."""
    open_i = buf.rfind("[")
    close_i = buf.rfind("]")
    safe_end = open_i if open_i > close_i else len(buf)  # hold an in-flight tag
    last = 0
    for m in SENT_BOUNDARY.finditer(buf, 0, safe_end):
        last = m.end()
    if last == 0:
        return "", buf
    return buf[:last], buf[last:]


class Session:
    """Per-connection state. One HA TTS request == one connection."""

    def __init__(self, up_writer, client_writer):
        self.up = up_writer
        self.client = client_writer
        self.streaming = False        # True once SynthesizeStart seen
        self.voice = None
        self.buf = ""
        self.got_text = False         # any SynthesizeChunk seen this session
        self.synth_sent = 0           # Synthesize events sent upstream
        self.audio_stops = 0          # AudioStop events received from upstream
        self.ha_done = False          # SynthesizeStop received from HA
        self.first_audio_sent = False
        self.stopped_sent = False
        self.tags: list[tuple[str, str]] = []
        self.lock = asyncio.Lock()
        self.done = asyncio.Event()

    async def _send_synth(self, text: str) -> None:
        await async_write_event(Synthesize(text=text, voice=self.voice).event(), self.up)
        self.synth_sent += 1

    async def feed(self, text: str) -> None:
        """Add text and emit any complete, tag-safe sentences."""
        self.buf += text
        while True:
            emit, self.buf = next_flush(self.buf)
            if not emit:
                break
            cleaned, tags = clean_segment(emit)
            if tags:
                self.tags.extend(tags)
            if cleaned.strip():
                await self._send_synth(cleaned)

    async def finalize(self) -> None:
        """HA finished sending text: flush remainder, fire tags, maybe finish."""
        emit, self.buf = self.buf, ""
        if emit.strip():
            cleaned, tags = clean_segment(emit)
            if tags:
                self.tags.extend(tags)
            if cleaned.strip():
                await self._send_synth(cleaned)
        if self.synth_sent == 0:  # reply was empty / tags-only
            await self._send_synth("Okay.")
        if self.streaming:
            log.info("stream end: emitted %d sentence(s) to Kokoro", self.synth_sent)
        self.ha_done = True
        if self.tags:
            log.info("stripped %s", [f"{n}:{v}" for n, v in self.tags])
            asyncio.get_running_loop().run_in_executor(None, record_tags_blocking, list(self.tags))
        await self.maybe_finish()

    async def maybe_finish(self) -> None:
        async with self.lock:
            if self.ha_done and not self.stopped_sent and self.audio_stops >= self.synth_sent:
                self.stopped_sent = True
                await async_write_event(SynthesizeStopped().event(), self.client)
                self.done.set()


async def pump_client_to_upstream(reader, sess: Session) -> None:
    while True:
        ev = await async_read_event(reader)
        if ev is None:
            break
        if SynthesizeStart.is_type(ev.type):
            sess.streaming = True
            sess.voice = SynthesizeStart.from_event(ev).voice
            log.info("stream start (HA is streaming text to TTS)")
            continue  # Kokoro doesn't understand start/chunk/stop; swallow
        if SynthesizeChunk.is_type(ev.type):
            sess.got_text = True
            await sess.feed(SynthesizeChunk.from_event(ev).text)
            continue
        if SynthesizeStop.is_type(ev.type):
            await sess.finalize()
            continue
        if Synthesize.is_type(ev.type):
            s = Synthesize.from_event(ev)
            if sess.streaming:
                # Backwards-compat duplicate of already-streamed text -> drop,
                # unless no chunks ever arrived (then this IS the content).
                if sess.got_text:
                    continue
                sess.voice = s.voice
                await sess.feed(s.text)
                continue
            # Non-streaming single-shot path (e.g. announce).
            sess.voice = s.voice
            cleaned, tags = clean_text(s.text)
            if tags:
                log.info("stripped %s from %r", [f"{n}:{v}" for n, v in tags], s.text[:120])
                asyncio.get_running_loop().run_in_executor(None, record_tags_blocking, tags)
            await async_write_event(Synthesize(text=cleaned, voice=s.voice).event(), sess.up)
            sess.synth_sent += 1
            continue
        await async_write_event(ev, sess.up)  # describe / anything else


async def pump_upstream_to_client(up_reader, sess: Session) -> None:
    while True:
        ev = await async_read_event(up_reader)
        if ev is None:
            break
        if ev.type == "info" and ev.data:
            for tts in ev.data.get("tts", []):
                tts["supports_synthesize_streaming"] = True
            await async_write_event(ev, sess.client)
            continue
        if not sess.streaming:
            await async_write_event(ev, sess.client)  # passthrough incl. AudioStop
            continue
        # Streaming: reframe per-sentence audio into one continuous stream.
        if AudioStart.is_type(ev.type):
            if not sess.first_audio_sent:
                sess.first_audio_sent = True
                await async_write_event(ev, sess.client)
            continue  # drop subsequent headers
        if AudioChunk.is_type(ev.type):
            await async_write_event(ev, sess.client)
            continue
        if AudioStop.is_type(ev.type):
            sess.audio_stops += 1
            await sess.maybe_finish()
            continue
        # ignore anything else in streaming mode


async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    try:
        up_reader, up_writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
    except OSError as err:
        log.error("upstream %s:%s unavailable: %s", UPSTREAM_HOST, UPSTREAM_PORT, err)
        writer.close()
        return
    sess = Session(up_writer, writer)
    tasks = [
        asyncio.create_task(pump_client_to_upstream(reader, sess)),
        asyncio.create_task(pump_upstream_to_client(up_reader, sess)),
    ]
    done_waiter = asyncio.create_task(sess.done.wait())
    try:
        await asyncio.wait([*tasks, done_waiter], return_when=asyncio.FIRST_COMPLETED)
        for t in (*tasks, done_waiter):
            t.cancel()
        for t in tasks:
            if t.done() and not t.cancelled():
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
    log.info("tag filter listening on %s:%s -> %s:%s (streaming adapter)", LISTEN_HOST, LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
