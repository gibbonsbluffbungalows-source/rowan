"""Transcribe a WAV via the wyoming-whisper service (diagnostic helper).
Run inside a container on the compose network (reaches wyoming-whisper:10300).
Usage: python wyoming_transcribe.py /path/to.wav"""
import asyncio, sys, wave
from wyoming.event import async_read_event, async_write_event, Event
from wyoming.audio import AudioChunk, AudioStart, AudioStop

PATH = sys.argv[1] if len(sys.argv) > 1 else "/tmp/bleed.wav"


async def main():
    w = wave.open(PATH, "rb")
    rate, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
    pcm = w.readframes(w.getnframes())
    r, wr = await asyncio.open_connection("wyoming-whisper", 10300)
    await async_write_event(Event(type="transcribe", data={"language": "en"}), wr)
    await async_write_event(AudioStart(rate=rate, width=width, channels=ch).event(), wr)
    step = 1024 * width * ch
    for i in range(0, len(pcm), step):
        await async_write_event(
            AudioChunk(audio=pcm[i:i + step], rate=rate, width=width, channels=ch).event(), wr)
    await async_write_event(AudioStop().event(), wr)
    while True:
        ev = await async_read_event(r)
        if ev is None:
            break
        if ev.type == "transcript":
            print("TRANSCRIPT:", repr((ev.data or {}).get("text")))
            break


asyncio.run(main())
