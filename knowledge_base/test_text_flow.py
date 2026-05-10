"""
Scripted text-only end-to-end test: text in → RAG → Claude → text out.

Verifies the integration contract:
  - Small-talk turns DON'T inject RAG (saves latency + tokens)
  - Clinical / navigational / emotional turns DO inject RAG
  - Claude's reply uses retrieved content (loose substring/keyword check)

Run after `python knowledge_base/ingest.py` finishes successfully.

Usage:
    python knowledge_base/test_text_flow.py
    python knowledge_base/test_text_flow.py -v    # also dump Lily's replies
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from anthropic import Anthropic

sys.path.insert(0, str(Path(__file__).parent))
from text_chat import BASE_SYSTEM_PROMPT, chat_turn  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Cases. Each is a single-turn — `expect_rag` is the integration contract:
# True  = the addendum MUST be injected (clinical/navigational/emotional)
# False = MUST be skipped (small talk, greetings)
#
# `reply_must_contain_any` is a loose check: at least one of these strings
# (case-insensitive) should show up in Lily's reply, indicating she used
# the retrieved content rather than confabulating.
# ──────────────────────────────────────────────────────────────────────────────

CASES = [
    # — Smalltalk: should SKIP RAG —
    {
        "user": "hey lily good morning",
        "expect_rag": False,
        "reply_must_contain_any": [],   # any reply OK
    },
    {
        "user": "thanks, that helps",
        "expect_rag": False,
        "reply_must_contain_any": [],
    },

    # — Clinical: must inject RAG and ground reply —
    {
        "user": "I have a really bad headache and I'm seeing spots",
        "expect_rag": True,
        "expect_action_in": ["escalate"],
        "reply_must_contain_any": ["preeclampsia", "emergency", "right away",
                                     "go in", "go to", "call", "doctor"],
    },
    {
        "user": "my feet are a bit swollen at the end of the day",
        "expect_rag": True,
        "expect_action_in": ["reassure", "self_care"],
        "reply_must_contain_any": ["normal", "common", "fluid", "feet up",
                                     "elevate", "rest"],
    },
    {
        "user": "I'm bleeding heavily and soaking a pad an hour after my c-section",
        "expect_rag": True,
        "expect_action_in": ["escalate"],
        "reply_must_contain_any": ["emergency", "911", "right away", "hospital",
                                     "go in", "now"],
    },

    # — Navigation: must inject RAG —
    {
        "user": "how do I sign up for WIC, I just had my baby",
        "expect_rag": True,
        "expect_action_in": ["navigate"],
        "reply_must_contain_any": ["wic", "office", "apply", "1-800",
                                     "signupwic", "income"],
    },

    # — Emotional: must inject RAG (PPD content) —
    {
        "user": "I just feel like I can't cope and I don't want to be here anymore",
        "expect_rag": True,
        "expect_action_in": ["escalate", "monitor"],
        "reply_must_contain_any": ["not alone", "depression", "doctor",
                                     "specialist", "support", "help"],
    },
]


# ──────────────────────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
NC = "\033[0m"


def _tick(ok: bool) -> str:
    return f"{GREEN}✓{NC}" if ok else f"{RED}✗{NC}"


async def run_case(client: Anthropic, case: dict, verbose: bool) -> bool:
    user = case["user"]
    expect_rag = case["expect_rag"]
    expected_actions = case.get("expect_action_in", [])
    must_contain = [s.lower() for s in case.get("reply_must_contain_any", [])]

    print(f'\n{DIM}user ▸{NC} "{user}"')

    # Each case starts fresh — single-turn, no history bleed across cases
    history: list[dict] = []
    reply, meta = await chat_turn(client, user, history, debug=False)

    rag_ok = (meta["rag_used"] == expect_rag)

    actions = [c.action_type for c, _ in meta["chunks"]]
    action_ok = (not expected_actions) or any(a in expected_actions for a in actions)

    reply_lower = reply.lower()
    keyword_ok = (not must_contain) or any(kw in reply_lower for kw in must_contain)

    print(f"  RAG injection:    {meta['rag_used']!s:<5} (expected {expect_rag!s:<5}) {_tick(rag_ok)}")
    if expected_actions:
        print(f"  action_type:      {actions if actions else '[]':<30} (expected one of {expected_actions}) {_tick(action_ok)}")
    if must_contain:
        matched = [kw for kw in must_contain if kw in reply_lower]
        print(f"  reply contains:   {matched or '(none)':<30} (any of {must_contain[:4]}{'...' if len(must_contain) > 4 else ''}) {_tick(keyword_ok)}")

    if verbose or not (rag_ok and action_ok and keyword_ok):
        print(f"  {DIM}lily ▸{NC} {reply}")

    return rag_ok and action_ok and keyword_ok


async def main_async(verbose: bool):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(f"{YELLOW}ANTHROPIC_API_KEY not set{NC}")
        sys.exit(1)
    client = Anthropic(api_key=api_key)

    print(f"Running {len(CASES)} text-flow cases (text → RAG → Claude → text)...")
    results = []
    for case in CASES:
        try:
            results.append(await run_case(client, case, verbose))
        except Exception as e:
            print(f"  {RED}EXCEPTION:{NC} {e!r}")
            results.append(False)

    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 60)
    if passed == total:
        print(f"{GREEN}ALL {passed}/{total} TEXT-FLOW CASES PASSED{NC}")
    else:
        print(f"{RED}{passed}/{total} PASSED — {total - passed} FAILED{NC}")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Print Lily's reply for every case (not just failing ones).")
    args = ap.parse_args()
    sys.exit(asyncio.run(main_async(args.verbose)))
