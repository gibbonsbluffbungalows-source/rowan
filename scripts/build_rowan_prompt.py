#!/usr/bin/env python3
"""Install the Rowan system prompt (persona + knowledge base) into HA's Ollama agent.

Concatenates prompts/rowan_system_prompt.md and Rowan_Knowledge_v15.md, writes the
result into the conversation subentry in .storage/core.config_entries, and sets
num_ctx. Run while Home Assistant is STOPPED (it rewrites .storage on shutdown):

    docker stop homeassistant
    python3 scripts/build_rowan_prompt.py
    docker start homeassistant
"""
import json
import shutil
from pathlib import Path

ROOT = Path("/home/rowan")
STORE = ROOT / "homeassistant/config/.storage/core.config_entries"
NUM_CTX = 16384

REMINDERS = """\
# FINAL REMINDERS (these override habits from your training)

You are Rowan, speaking aloud to a guest. Calm, direct, understated — a local friend, not a customer-service bot. Never open with filler like "Sure thing!" and never close with "Let me know if you need anything else."

Plain spoken sentences only — no markdown, no asterisks, no bullet points, no emoji.

Answer from the knowledge base. Match the section to the question: coffee questions get coffee shops, restaurant questions get restaurants, and check the stated hours and time zone before suggesting a place for a specific time of day. If the knowledge base doesn't cover it, say so plainly and offer to check with the host — never invent names, addresses, phone numbers, or hours.

Keep it brief. One or two sentences for simple questions, a few more for recommendations. Pick the best option for this guest instead of listing everything.
"""

persona = (ROOT / "prompts/rowan_system_prompt.md").read_text()
kb = (ROOT / "Rowan_Knowledge_v15.md").read_text()
prompt = (
    persona.rstrip()
    + "\n\n---\n\n# KNOWLEDGE BASE\n\n"
    + kb.strip()
    + "\n\n---\n\n"
    + REMINDERS
)

shutil.copy2(STORE, str(STORE) + ".bak")
data = json.loads(STORE.read_text())
sub = next(
    s
    for e in data["data"]["entries"]
    if e["domain"] == "ollama"
    for s in e["subentries"]
    if s["title"] == "Rowan"
)
sub["data"]["prompt"] = prompt
sub["data"]["num_ctx"] = float(NUM_CTX)
STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(f"prompt: {len(prompt)} chars (~{len(prompt)//4} tokens), num_ctx: {NUM_CTX}")
