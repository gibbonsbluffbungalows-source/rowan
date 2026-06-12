#!/usr/bin/env python3
"""A/B Rowan's current voice (Kokoro bm_george) against ElevenLabs, on the Jabra.

Why: George sounds gravelly-good but choppy — start/stop rhythm, questions that
don't rise. ElevenLabs' prosody is exactly that gap. This plays the SAME line in
both so you can hear it.

Setup (one time):
  1. Make a free ElevenLabs account -> Profile -> API key.
  2. Put it in /home/rowan/.elevenlabs_key   (chmod 600; gitignored)

Usage:
  rowan_voice_ab.py --list-voices                 # see voice ids on your account
  rowan_voice_ab.py [--voice-id ID] [--model M]   # A/B the built-in test lines
  rowan_voice_ab.py --from-log 8                   # use last 8 real logged replies
  rowan_voice_ab.py --text "Would you like a trail?"
  rowan_voice_ab.py --questions                    # only logged replies ending in '?'

For each line it plays A = George (Kokoro, local), then B = ElevenLabs, and lets
you jot a quick preference to tag-filter-data/voice_ab_notes.jsonl.
NOTE: pauses the satellite for the session (Jabra is single-owner), resumes after.
"""
import argparse
import json
import subprocess
import sys
import urllib.request
import urllib.error
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / ".elevenlabs_key"
NOTES = ROOT / "tag-filter-data" / "voice_ab_notes.jsonl"
REPLIES = ROOT / "tag-filter-data" / "feedback.jsonl"

PI = "pi@100.87.194.126"
JABRA = "plughw:CARD=USB,DEV=0"
KOKORO_CONTAINER = "kokoro-wyoming"

# Default ElevenLabs voice: "Clyde" — a gravelly middle-aged male premade voice
# (closest premade to George's character). Override with --voice-id after
# --list-voices. Multilingual_v2 also handles Spanish (Rowan ES).
DEFAULT_VOICE_ID = "2EiwWnXFnvU5JabPnv8n"  # Clyde
DEFAULT_MODEL = "eleven_multilingual_v2"

TEST_LINES = [
    "Would you like me to point you toward a good trail for the morning?",
    "For coffee on the way out, I'd point you to Creekside Cafe. It's an easy stop heading toward the falls.",
    "You're looking right out over the bluff. The valley drops away below you. And on a clear day you can see all the way to the ridgeline.",
    "Checkout's at 10 in the morning. Is there anything else you need before you head out?",
    "It's all one word, I'll spell it: A, H, H, W, H, A, T, A, V, I, E, W, and it ends with an exclamation point.",
]


def read_key():
    if KEY_FILE.exists():
        k = KEY_FILE.read_text().strip()
        if k:
            return k
    sys.exit(f"No ElevenLabs key. Put it in {KEY_FILE} (chmod 600). "
             "Get one free at elevenlabs.io -> Profile -> API key.")


def el_list_voices(key):
    req = urllib.request.Request("https://api.elevenlabs.io/v1/voices",
                                 headers={"xi-api-key": key})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    for v in data.get("voices", []):
        labels = v.get("labels", {}) or {}
        desc = ", ".join(f"{k}={labels[k]}" for k in ("gender", "age", "accent", "descriptive") if k in labels)
        print(f"  {v['voice_id']}  {v.get('name','?'):16}  {desc}")


def el_synth(text, voice_id, model, key, out="/tmp/el.wav"):
    body = json.dumps({
        "text": text,
        "model_id": model,
        "voice_settings": {"stability": 0.35, "similarity_boost": 0.8,
                           "style": 0.4, "use_speaker_boost": True},
    }).encode()
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_22050"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            pcm = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs error {e.code}: {e.read().decode()[:200]}")
    w = wave.open(out, "wb")
    w.setframerate(22050); w.setsampwidth(2); w.setnchannels(1); w.writeframes(pcm); w.close()
    return out


def kokoro_synth(text, voice="bm_george", out="/tmp/george.wav"):
    script = (
        "import asyncio,sys,wave\n"
        "from wyoming.client import AsyncTcpClient\n"
        "from wyoming.tts import Synthesize,SynthesizeVoice\n"
        "from wyoming.audio import AudioChunk,AudioStart,AudioStop\n"
        "async def main():\n"
        "  async with AsyncTcpClient('127.0.0.1',10210) as c:\n"
        "    await c.write_event(Synthesize(text=sys.argv[1],voice=SynthesizeVoice(name=sys.argv[2])).event())\n"
        "    rate=width=ch=None; frames=b''\n"
        "    while True:\n"
        "      e=await c.read_event()\n"
        "      if e is None: break\n"
        "      if AudioStart.is_type(e.type):\n"
        "        a=AudioStart.from_event(e); rate,width,ch=a.rate,a.width,a.channels\n"
        "      elif AudioChunk.is_type(e.type): frames+=AudioChunk.from_event(e).audio\n"
        "      elif AudioStop.is_type(e.type): break\n"
        "    w=wave.open('/tmp/george.wav','wb'); w.setframerate(rate or 22050)\n"
        "    w.setsampwidth(width or 2); w.setnchannels(ch or 1); w.writeframes(frames); w.close()\n"
        "asyncio.run(main())\n"
    )
    subprocess.run(["docker", "exec", KOKORO_CONTAINER, "python3", "-c", script, text, voice], check=True)
    subprocess.run(["docker", "cp", f"{KOKORO_CONTAINER}:/tmp/george.wav", out], check=True)
    return out


def play(wavpath, label):
    print(f"   ♪ {label}")
    subprocess.run(["scp", "-q", wavpath, f"{PI}:/tmp/ab.wav"], check=True)
    subprocess.run(["ssh", PI, f"aplay -q -D {JABRA} /tmp/ab.wav"], check=True)


def pick_lines(args):
    if args.text:
        return [args.text]
    if args.from_log or args.questions:
        reps = []
        if REPLIES.exists():
            for ln in REPLIES.read_text().splitlines():
                try:
                    reps.append(json.loads(ln)["text"])
                except Exception:
                    pass
        if args.questions:
            reps = [t for t in reps if t.rstrip().endswith("?")]
        n = args.from_log or 5
        return reps[-n:] if reps else []
    return TEST_LINES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--voice-id", default=DEFAULT_VOICE_ID)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--from-log", type=int, metavar="N", help="use last N logged replies")
    ap.add_argument("--questions", action="store_true", help="logged replies ending in '?' only")
    ap.add_argument("--text", help="A/B a single custom line")
    args = ap.parse_args()

    key = read_key()
    if args.list_voices:
        el_list_voices(key)
        return

    lines = pick_lines(args)
    if not lines:
        sys.exit("No lines to test (log empty?). Try the built-in set or --text.")
    print(f"A/B {len(lines)} line(s): A=George(Kokoro)  B=ElevenLabs voice={args.voice_id} model={args.model}\n")

    subprocess.run(["ssh", PI, "sudo -n systemctl stop wyoming-satellite"], check=False)
    print("(satellite paused)\n")
    try:
        for i, text in enumerate(lines, 1):
            print(f"[{i}/{len(lines)}] \"{text}\"")
            try:
                play(kokoro_synth(text), "A — George (Kokoro)")
                play(el_synth(text, args.voice_id, args.model, key), "B — ElevenLabs")
            except subprocess.CalledProcessError as e:
                print(f"   (playback/render failed: {e})")
            pref = input("   prefer [a/b/=]  note?> ").strip()
            if pref:
                with NOTES.open("a") as f:
                    f.write(json.dumps({"text": text, "voice_id": args.voice_id,
                                        "model": args.model, "pref": pref}) + "\n")
            print()
    finally:
        subprocess.run(["ssh", PI, "sudo -n systemctl start wyoming-satellite"], check=False)
        print("(satellite resumed)")


if __name__ == "__main__":
    main()
