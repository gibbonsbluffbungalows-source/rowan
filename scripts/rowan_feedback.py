#!/usr/bin/env python3
"""Rowan voice feedback harness — review tool.

The tag-filter logs every spoken reply to tag-filter-data/feedback.jsonl
(automatic, no effort). This tool lets you rate them by ear over time so the
'stiff' ones become prompt/voice tuning material.

Files (host paths):
  tag-filter-data/feedback.jsonl          replies (appended by the filter)
  tag-filter-data/feedback_ratings.jsonl  your ratings (appended here, by id)

Usage:
  rowan_feedback.py stats
  rowan_feedback.py review [--play]   # --play synthesizes + plays on the Jabra
  rowan_feedback.py report [--out FILE]

--play renders each reply through Kokoro and plays it on the Pi's Jabra. It
stops the satellite once for the session and restarts it at the end (so the
wake word is offline while you review). Audio is identical to what guests hear
(Kokoro is deterministic for a given text+voice+speed).
"""
import argparse
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "tag-filter-data"
REPLIES = DATA / "feedback.jsonl"
RATINGS = DATA / "feedback_ratings.jsonl"

PI = "pi@100.87.194.126"
JABRA = "plughw:CARD=USB,DEV=0"
# Render path: talk to Kokoro directly (NOT through the tag-filter, so review
# synth does not pollute feedback.jsonl). kokoro-wyoming is internal to the
# compose network, so we render from inside that container.
KOKORO_CONTAINER = "kokoro-wyoming"


def _load_jsonl(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _rated_ids():
    return {r["id"] for r in _load_jsonl(RATINGS) if "id" in r}


def cmd_stats(args):
    replies = _load_jsonl(REPLIES)
    ratings = _load_jsonl(RATINGS)
    rated = _rated_ids()
    by = {}
    for r in ratings:
        by[r.get("rating")] = by.get(r.get("rating"), 0) + 1
    print(f"replies logged : {len(replies)}")
    print(f"rated          : {len(rated)}  ({by.get('good',0)} good, {by.get('stiff',0)} stiff)")
    print(f"unrated        : {len([r for r in replies if r.get('id') not in rated])}")


def _render_and_play(text, voice):
    """Render text via Kokoro inside its container, copy WAV to Pi, aplay it."""
    script = (
        "import asyncio,sys,wave\n"
        "from wyoming.client import AsyncTcpClient\n"
        "from wyoming.tts import Synthesize,SynthesizeVoice\n"
        "from wyoming.audio import AudioChunk,AudioStart,AudioStop\n"
        "TEXT=sys.argv[1]; VOICE=sys.argv[2] or None\n"
        "async def main():\n"
        "  async with AsyncTcpClient('127.0.0.1',10210) as c:\n"
        "    v=SynthesizeVoice(name=VOICE) if VOICE else None\n"
        "    await c.write_event(Synthesize(text=TEXT,voice=v).event())\n"
        "    rate=width=ch=None; frames=b''\n"
        "    while True:\n"
        "      e=await c.read_event()\n"
        "      if e is None: break\n"
        "      if AudioStart.is_type(e.type):\n"
        "        a=AudioStart.from_event(e); rate,width,ch=a.rate,a.width,a.channels\n"
        "      elif AudioChunk.is_type(e.type): frames+=AudioChunk.from_event(e).audio\n"
        "      elif AudioStop.is_type(e.type): break\n"
        "    w=wave.open('/tmp/fb.wav','wb'); w.setframerate(rate or 22050)\n"
        "    w.setsampwidth(width or 2); w.setnchannels(ch or 1); w.writeframes(frames); w.close()\n"
        "asyncio.run(main())\n"
    )
    subprocess.run(["docker", "exec", KOKORO_CONTAINER, "python3", "-c", script, text, voice or ""],
                   check=True)
    subprocess.run(["docker", "cp", f"{KOKORO_CONTAINER}:/tmp/fb.wav", "/tmp/fb.wav"], check=True)
    subprocess.run(["scp", "-q", "/tmp/fb.wav", f"{PI}:/tmp/fb.wav"], check=True)
    subprocess.run(["ssh", PI, f"aplay -q -D {JABRA} /tmp/fb.wav"], check=True)


def cmd_review(args):
    replies = _load_jsonl(REPLIES)
    rated = _rated_ids()
    todo = [r for r in replies if r.get("id") and r["id"] not in rated]
    if not todo:
        print("Nothing to review — all caught up.")
        return
    print(f"{len(todo)} reply(ies) to review. [g]ood  [s]tiff  [enter]=skip  [q]uit\n")

    sat_stopped = False
    if args.play:
        subprocess.run(["ssh", PI, "sudo -n systemctl stop wyoming-satellite"], check=False)
        sat_stopped = True
        print("(satellite paused for review)\n")
    try:
        for i, r in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}]  {r.get('ts','')}  voice={r.get('voice')}")
            print(f'   "{r["text"]}"')
            if args.play:
                try:
                    _render_and_play(r["text"], r.get("voice"))
                except Exception as e:
                    print(f"   (play failed: {e})")
            try:
                ans = input("   rate> ").strip().lower()
            except EOFError:
                break
            if ans == "q":
                break
            if ans not in ("g", "s"):
                print()
                continue
            note = input("   note (optional)> ").strip()
            rating = "good" if ans == "g" else "stiff"
            with RATINGS.open("a") as f:
                f.write(json.dumps({"id": r["id"], "rating": rating, "note": note},
                                   ensure_ascii=False) + "\n")
            print(f"   saved: {rating}\n")
    finally:
        if sat_stopped:
            subprocess.run(["ssh", PI, "sudo -n systemctl start wyoming-satellite"], check=False)
            print("(satellite resumed)")


def cmd_report(args):
    replies = {r["id"]: r for r in _load_jsonl(REPLIES) if "id" in r}
    ratings = _load_jsonl(RATINGS)
    lines = ["# Rowan voice feedback report\n"]
    for label in ("stiff", "good"):
        rows = [x for x in ratings if x.get("rating") == label]
        lines.append(f"\n## {label.upper()} ({len(rows)})\n")
        for x in rows:
            rep = replies.get(x["id"], {})
            note = f"  — _{x['note']}_" if x.get("note") else ""
            lines.append(f'- "{rep.get("text","?")}"{note}')
    out = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(out)
        print(f"wrote {args.out}")
    else:
        print(out)


def main():
    p = argparse.ArgumentParser(description="Rowan voice feedback review tool")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    rv = sub.add_parser("review")
    rv.add_argument("--play", action="store_true", help="synthesize + play each on the Jabra")
    rp = sub.add_parser("report")
    rp.add_argument("--out", help="write markdown report to this file")
    args = p.parse_args()
    {"stats": cmd_stats, "review": cmd_review, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
