#!/usr/bin/env python3
"""Synthesize a line through a Wyoming TTS server for voice A/B testing.

Used to audition Kokoro voices without touching the live HA pipeline. Connects
to the Wyoming TTS server (the tag-filter on :10210 passes clean text straight
through to kokoro-wyoming), collects the audio, and writes a wav.

    python3 tts_sample.py --list
    python3 tts_sample.py --voice bm_lewis --text "..." --out /tmp/lewis.wav
"""
import argparse
import asyncio
import wave

from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize, SynthesizeVoice
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.info import Describe, Info


async def list_voices(host, port):
    async with AsyncTcpClient(host, port) as client:
        await client.write_event(Describe().event())
        while True:
            ev = await client.read_event()
            if ev is None:
                break
            if Info.is_type(ev.type):
                info = Info.from_event(ev)
                for prog in info.tts:
                    for v in prog.voices:
                        langs = ",".join(v.languages or [])
                        print(f"{v.name}\t{langs}")
                return


async def synth(host, port, voice, text, out):
    async with AsyncTcpClient(host, port) as client:
        syn = Synthesize(text=text, voice=SynthesizeVoice(name=voice))
        await client.write_event(syn.event())
        rate = width = channels = None
        frames = bytearray()
        while True:
            ev = await client.read_event()
            if ev is None:
                break
            if AudioStart.is_type(ev.type):
                a = AudioStart.from_event(ev)
                rate, width, channels = a.rate, a.width, a.channels
            elif AudioChunk.is_type(ev.type):
                frames += AudioChunk.from_event(ev).audio
            elif AudioStop.is_type(ev.type):
                break
        with wave.open(out, "wb") as w:
            w.setnchannels(channels or 1)
            w.setsampwidth(width or 2)
            w.setframerate(rate or 22050)
            w.writeframes(bytes(frames))
        secs = len(frames) / ((rate or 22050) * (width or 2) * (channels or 1))
        print(f"wrote {out}: {secs:.1f}s @ {rate}Hz voice={voice}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10210)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--voice", default="bm_lewis")
    ap.add_argument("--text", default="")
    ap.add_argument("--out", default="/tmp/tts_sample.wav")
    args = ap.parse_args()
    if args.list:
        asyncio.run(list_voices(args.host, args.port))
    else:
        asyncio.run(synth(args.host, args.port, args.voice, args.text, args.out))


if __name__ == "__main__":
    main()
