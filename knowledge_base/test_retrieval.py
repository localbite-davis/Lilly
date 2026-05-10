"""
Validation harness for the RAG knowledge base.

Run after ingest.py finishes. Each query is fed through the full retrieval
pipeline (classify → retrieve) and the top chunk's metadata is compared
against expectations.

A failing test means the knowledge base needs more/better chunks for that
topic — fix ingestion before wiring RAG into the voice pipeline.

Usage:
    python knowledge_base/test_retrieval.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from retrieve import rag_for_turn  # noqa: E402


TEST_CASES = [
    {
        "query": "I have a really bad headache and I can see spots",
        "expect_action_type": "escalate",
        "expect_tier_signal": "hand_off",
    },
    {
        "query": "my feet are a bit swollen at the end of the day",
        "expect_action_type": "reassure",
        "expect_tier_signal": "handle",
    },
    {
        "query": "I'm bleeding more than a pad an hour after my C-section",
        "expect_action_type": "escalate",
        "expect_tier_signal": "hand_off",
    },
    {
        "query": "my baby won't latch and my nipples are really sore",
        "expect_action_type": "self_care",
        "expect_tier_signal": "handle",
    },
    {
        "query": "I feel like I can't cope and I don't want to be here anymore",
        "expect_action_type": "escalate",
        "expect_tier_signal": "hand_up",
    },
    {
        "query": "how do I apply for WIC I just had my baby",
        "expect_action_type": "navigate",
        "expect_tier_signal": "none",
    },
    {
        "query": "is it normal to still be bleeding 4 weeks after giving birth",
        "expect_action_type": "monitor",
        "expect_tier_signal": "hand_up",
    },
    {
        "query": "I'm feeling really tired today",
        "expect_action_type": "reassure",
        "expect_tier_signal": "handle",
    },
]


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
DIM = "\033[2m"
NC = "\033[0m"


def _tick(ok: bool) -> str:
    return f"{GREEN}✓{NC}" if ok else f"{RED}✗{NC}"


async def run_one(case: dict) -> bool:
    query = case["query"]
    expected_action = case["expect_action_type"]
    expected_tier = case["expect_tier_signal"]

    print(f'\nQuery: "{query}"')

    try:
        result = await rag_for_turn(query)
    except Exception as e:
        print(f"  {RED}EXCEPTION:{NC} {e}")
        return False

    if not result.chunks:
        print(f"  {YELLOW}No chunks retrieved{NC}  "
              f"(classification: clinical={result.classification.is_clinical}, "
              f"navigational={result.classification.is_navigational}, "
              f"emotional={result.classification.is_emotional})")
        return False

    top_chunk, top_dist = result.chunks[0]
    similarity = 1 - top_dist
    action_ok = top_chunk.action_type == expected_action
    tier_ok = top_chunk.tier_signal == expected_tier

    print(f"  Retrieved: [{top_chunk.source}] {top_chunk.subtopic[:60]}")
    print(f"  action_type:  {top_chunk.action_type:10s} (expected {expected_action}) {_tick(action_ok)}")
    print(f"  tier_signal:  {top_chunk.tier_signal:10s} (expected {expected_tier}) {_tick(tier_ok)}")
    print(f"  similarity:   {similarity:.2f}")
    print(f"  {DIM}classification: clinical={result.classification.is_clinical} "
          f"nav={result.classification.is_navigational} "
          f"emotional={result.classification.is_emotional} "
          f"severity={result.classification.severity_signal}{NC}")

    return action_ok and tier_ok


async def main():
    print(f"Running {len(TEST_CASES)} test cases...")
    results = []
    for case in TEST_CASES:
        results.append(await run_one(case))

    passed = sum(results)
    total = len(results)
    print("\n" + "=" * 60)
    if passed == total:
        print(f"{GREEN}ALL {passed}/{total} TESTS PASSED{NC}")
    else:
        print(f"{RED}{passed}/{total} TESTS PASSED — {total - passed} FAILED{NC}")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
