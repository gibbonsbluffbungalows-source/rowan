#!/usr/bin/env python3
"""Nightly pipeline self-test. Runs INSIDE the homeassistant container
(wyoming lib + localhost service ports available; HA is host-networked).

Checks, in order:
  1. TTS  — kokoro via tag-filter (:10210) synthesizes a short phrase
  2. STT  — whisper (:10300) transcribes it back, must contain 'checkout'
  3. LLM  — conversation.rowan answers the checkout question, must say 10
  4. WX   — local weather sensor updated within the last 15 minutes

Exit 0 all good (silent); exit 1 with reasons on stdout — the
rowan_nightly_self_test automation pushes that to Mark's phone.
Deploy: docker cp scripts/self_test.py homeassistant:/config/self_test.py
"""
import asyncio
import json
import sys
import urllib.request
from datetime import datetime, timezone

from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.event import async_read_event, async_write_event
from wyoming.tts import Synthesize, SynthesizeVoice

HA = "http://127.0.0.1:8123"
TOKEN_FILE = "/config/.self_test_token"
PHRASE = "Checkout is at ten in the morning."

failures: list[str] = []


def token() -> str:
    return open(TOKEN_FILE).read().strip()


def ha_api(path: str, payload: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{HA}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


async def tts_stt() -> None:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 10210), 10
        )
        await async_write_event(
            Synthesize(text=PHRASE, voice=SynthesizeVoice(name="bm_lewis")).event(), writer
        )
        chunks, fmt = [], None
        while True:
            ev = await asyncio.wait_for(async_read_event(reader), 30)
            if ev is None:
                raise RuntimeError("TTS closed early")
            if AudioStart.is_type(ev.type):
                a = AudioStart.from_event(ev)
                fmt = (a.rate, a.width, a.channels)
            elif AudioChunk.is_type(ev.type):
                chunks.append(AudioChunk.from_event(ev))
            elif AudioStop.is_type(ev.type):
                break
        writer.close()
        if not chunks:
            raise RuntimeError("TTS returned no audio")
    except Exception as err:
        failures.append(f"TTS: {err}")
        return

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 10300), 10
        )
        await async_write_event(Transcribe(language="en").event(), writer)
        await async_write_event(
            AudioStart(rate=fmt[0], width=fmt[1], channels=fmt[2]).event(), writer
        )
        for c in chunks:
            await async_write_event(c.event(), writer)
        await async_write_event(AudioStop().event(), writer)
        while True:
            ev = await asyncio.wait_for(async_read_event(reader), 60)
            if ev is None:
                raise RuntimeError("STT closed early")
            if Transcript.is_type(ev.type):
                text = Transcript.from_event(ev).text.lower()
                if "checkout" not in text and "check out" not in text:
                    raise RuntimeError(f"transcript mismatch: {text!r}")
                break
        writer.close()
    except Exception as err:
        failures.append(f"STT: {err}")


def llm() -> None:
    try:
        resp = ha_api(
            "/api/conversation/process",
            {"text": "What time is checkout?", "agent_id": "conversation.rowan"},
        )
        speech = resp["response"]["speech"]["plain"]["speech"].lower()
        if "10" not in speech and "ten" not in speech:
            raise RuntimeError(f"unexpected answer: {speech[:120]!r}")
    except Exception as err:
        failures.append(f"LLM: {err}")


def weather() -> None:
    try:
        req = urllib.request.Request(
            f"{HA}/api/states/sensor.ws_2902_gibbonsbluff_outdoor_temperature",
            headers={"Authorization": f"Bearer {token()}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            state = json.loads(resp.read())
        age = datetime.now(timezone.utc) - datetime.fromisoformat(state["last_updated"])
        if state["state"] in ("unavailable", "unknown") or age.total_seconds() > 900:
            raise RuntimeError(
                f"local weather stale (state={state['state']}, {age.total_seconds():.0f}s old)"
            )
    except Exception as err:
        failures.append(f"WX: {err} (cloud fallback still covers the brief)")


asyncio.run(tts_stt())
llm()
weather()

if failures:
    print("; ".join(failures))
    sys.exit(1)
print("all checks passed")
