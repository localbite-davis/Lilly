"""
Text-based conversation harness for testing the Lily RAG → Claude flow.

No audio, no STT, no TTS — just type messages, watch Lily respond, and
see exactly what RAG injected into Claude's system prompt for each turn.

Usage:
    python knowledge_base/text_chat.py             # interactive
    python knowledge_base/text_chat.py --debug     # also print the addendum
                                                    # injected on each turn

Type /quit, /exit, or Ctrl+C to end. Type /reset to clear history.

This is the same integration pattern session.py will eventually use:

    rag = await rag_for_turn(user_text, ...)
    if rag.has_context:
        system_prompt = base_prompt + "\\n\\n" + rag.addendum
    else:
        system_prompt = base_prompt
    response = claude.messages.create(system=system_prompt, messages=history)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Load .env early so ANTHROPIC_API_KEY is available
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from anthropic import Anthropic

sys.path.insert(0, str(Path(__file__).parent))
from retrieve import rag_for_turn  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Lily's persona for the text harness. Stripped down — no tools, no patient
# context — so we can focus on testing whether RAG is being injected
# correctly and whether Claude grounds responses in retrieved content.
# ──────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """\
You are Lily, a warm and knowledgeable maternal health companion for
pregnant women and new mothers. Your tone is empathetic, plain-spoken,
and never clinical or rushed.

Hard limits:
- Do not diagnose. Never use the word "diagnose" in your replies.
- Do not recommend new medications or supplements.
- If she asks "should I go in?", your answer is never "no, you'll be fine."
- For emergencies, you stay on the line and tell her help is on the way.

When [RETRIEVED MEDICAL CONTEXT] is provided in your system prompt, ground
your reply in that content. Do not quote it verbatim. Do not tell her you
"looked it up" — speak as if you know it.

Keep replies SHORT (1-3 sentences) — they will be spoken aloud."""


# ──────────────────────────────────────────────────────────────────────────────
# Colors
# ──────────────────────────────────────────────────────────────────────────────

CYAN = "\033[36m"
GREEN = "\033[32m"
DIM = "\033[2m"
BOLD = "\033[1m"
YELLOW = "\033[33m"
NC = "\033[0m"

MODEL = "claude-sonnet-4-6"
FALLBACK_MODEL = "claude-haiku-4-5-20251001"


# ──────────────────────────────────────────────────────────────────────────────

async def chat_turn(
    client: Anthropic,
    user_text: str,
    history: list[dict],
    debug: bool,
) -> tuple[str, dict]:
    """
    Run one conversational turn:
      1. Classify + retrieve via rag_for_turn
      2. If context retrieved → append addendum to system prompt
      3. Call Claude with messages history
      4. Return assistant reply text + RAG metadata for inspection
    """
    rag = await rag_for_turn(user_text, base_system_prompt=BASE_SYSTEM_PROMPT)

    # Decide whether to inject RAG. has_context covers both clinical/nav
    # (chunks retrieved) and emotional (reasoning block always added).
    if rag.has_context and rag.addendum:
        system_prompt = BASE_SYSTEM_PROMPT + "\n\n" + rag.addendum
        rag_used = True
    else:
        system_prompt = BASE_SYSTEM_PROMPT
        rag_used = False

    # Append the user turn to history before sending
    history.append({"role": "user", "content": user_text})

    def call_claude(model: str):
        return client.messages.create(
            model=model,
            max_tokens=400,
            temperature=0.4,
            system=system_prompt,
            messages=history,
        )

    try:
        resp = await asyncio.to_thread(call_claude, MODEL)
    except Exception as e:
        print(f"{YELLOW}({MODEL} failed, falling back to {FALLBACK_MODEL}: {e}){NC}")
        resp = await asyncio.to_thread(call_claude, FALLBACK_MODEL)

    reply = "".join(b.text for b in resp.content if b.type == "text").strip()
    history.append({"role": "assistant", "content": reply})

    meta = {
        "rag_used": rag_used,
        "classification": rag.classification,
        "chunks": rag.chunks,
        "addendum": rag.addendum,
    }
    return reply, meta


def print_rag_meta(meta: dict, verbose: bool):
    cls = meta["classification"]
    flags = []
    if cls.is_clinical: flags.append("clinical")
    if cls.is_navigational: flags.append("navigational")
    if cls.is_emotional: flags.append("emotional")
    flags_str = ",".join(flags) or "smalltalk"

    if meta["rag_used"]:
        chunk_summary = ", ".join(
            f"[{c.source}:{c.action_type}]" for c, _ in meta["chunks"][:3]
        ) or "(no chunks, reasoning block only)"
        print(f"{DIM}    RAG: yes  | {flags_str}  | {chunk_summary}{NC}")
    else:
        print(f"{DIM}    RAG: skipped  | {flags_str}{NC}")

    if verbose and meta["addendum"]:
        print(f"{DIM}    ── Addendum injected ─────────────────────────{NC}")
        for line in meta["addendum"].splitlines():
            print(f"{DIM}    │ {line}{NC}")
        print(f"{DIM}    ──────────────────────────────────────────────{NC}")


async def main_async(debug: bool):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(f"{YELLOW}ANTHROPIC_API_KEY not set — check .env{NC}")
        sys.exit(1)

    client = Anthropic(api_key=api_key)
    history: list[dict] = []

    print(f"{BOLD}🌸 Lily text chat — type to talk, /quit to exit, /reset to clear{NC}")
    print(f"{DIM}   model: {MODEL}  |  RAG injection: only on clinical/nav/emotional turns{NC}\n")

    loop = asyncio.get_event_loop()

    while True:
        try:
            user_text = await loop.run_in_executor(
                None, lambda: input(f"{CYAN}you ▸{NC} ")
            )
        except (EOFError, KeyboardInterrupt):
            print()
            break

        user_text = user_text.strip()
        if not user_text:
            continue
        if user_text in ("/quit", "/exit"):
            break
        if user_text == "/reset":
            history.clear()
            print(f"{DIM}    (history cleared){NC}\n")
            continue

        try:
            reply, meta = await chat_turn(client, user_text, history, debug)
        except Exception as e:
            print(f"{YELLOW}error: {e}{NC}")
            continue

        print(f"{GREEN}lily ▸{NC} {reply}")
        print_rag_meta(meta, verbose=debug)
        print()

    print(f"\n{DIM}bye{NC}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-d", "--debug", action="store_true",
                    help="Print the full RAG addendum injected on each turn.")
    args = ap.parse_args()
    try:
        asyncio.run(main_async(args.debug))
    except KeyboardInterrupt:
        print()
