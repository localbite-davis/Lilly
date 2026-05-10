"""
RAG retrieval pipeline — runs at call time inside the voice loop.

Public API:
    classify_turn(text)            → Classification (lightweight Claude Haiku call)
    retrieve_clinical(...)         → list[LilyChunk] from clinical KB
    retrieve_navigational(...)     → list[LilyChunk] from navigation chunks
    assemble_prompt(...)           → final string to put in Claude's system prompt
    rag_for_turn(text, ...)        → orchestrates classify → retrieve → assemble

Use `rag_for_turn()` from the voice pipeline as a single entry point.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# Load .env BEFORE constructing the Anthropic client (which reads
# ANTHROPIC_API_KEY at init time). Walks up looking for a .env file.
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import chromadb
from anthropic import Anthropic

sys.path.insert(0, str(Path(__file__).parent))
from schema import LilyChunk  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

CHROMA_DIR = Path(__file__).parent / "chroma_db"
COLLECTION_NAME = "lily_medical"

# Cosine distance threshold — Chroma returns "distance" where lower = more
# similar. With cosine, distance = 1 - similarity. all-MiniLM-L6-v2 produces
# higher distances than OpenAI embeddings, so we use a generous threshold.
# Anything past 1.0 is essentially noise.
DEFAULT_DISTANCE_THRESHOLD = 1.2

# Model for query classification. Haiku 4.5 is fast + cheap.
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"


# ──────────────────────────────────────────────────────────────────────────────
# Lazy singletons
# ──────────────────────────────────────────────────────────────────────────────

_chroma_client = None
_collection = None
_anthropic = None


def _get_collection():
    global _chroma_client, _collection
    if _collection is None:
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _chroma_client.get_collection(name=COLLECTION_NAME)
    return _collection


def _get_anthropic() -> Anthropic:
    global _anthropic
    if _anthropic is None:
        _anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _anthropic


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: Query classification
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Classification:
    is_clinical: bool = False
    is_navigational: bool = False
    is_emotional: bool = False
    symptom_keywords: List[str] = field(default_factory=list)
    gestational_context: str = "unknown"   # T1|T2|T3|postpartum_early|postpartum_late|unknown
    severity_signal: str = "none"          # none|low|medium|high

    @classmethod
    def from_dict(cls, d: dict) -> "Classification":
        return cls(
            is_clinical=bool(d.get("is_clinical", False)),
            is_navigational=bool(d.get("is_navigational", False)),
            is_emotional=bool(d.get("is_emotional", False)),
            symptom_keywords=list(d.get("symptom_keywords", []) or []),
            gestational_context=str(d.get("gestational_context", "unknown")),
            severity_signal=str(d.get("severity_signal", "none")),
        )


CLASSIFIER_PROMPT = """\
Given this message from a pregnant or postpartum patient, classify it.

Message: "{text}"

Return JSON only — no prose, no markdown fences:
{{
  "is_clinical": true/false,
  "is_navigational": true/false,
  "is_emotional": true/false,
  "symptom_keywords": ["list", "of", "keywords"],
  "gestational_context": "T1|T2|T3|postpartum_early|postpartum_late|unknown",
  "severity_signal": "none|low|medium|high"
}}

Rules:
- is_clinical: physical symptoms, vitals, medications, anything medical
- is_navigational: WIC, Medicaid, insurance, appointments, transportation
- is_emotional: distress, sadness, anxiety, isolation, mood
- severity_signal high: signs of emergency (severe bleeding, severe headache+vision changes, suicidal ideation, chest pain, seizure)
"""


def classify_turn(text: str) -> Classification:
    """Synchronous classification — call from a thread if you need async."""
    client = _get_anthropic()
    resp = client.messages.create(
        model=CLASSIFIER_MODEL,
        max_tokens=300,
        temperature=0,
        messages=[{"role": "user", "content": CLASSIFIER_PROMPT.format(text=text)}],
    )
    raw = next((c.text for c in resp.content if c.type == "text"), "{}")
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").lstrip("json").strip()
    try:
        return Classification.from_dict(json.loads(raw))
    except json.JSONDecodeError:
        return Classification()  # safe default


async def classify_turn_async(text: str) -> Classification:
    return await asyncio.to_thread(classify_turn, text)


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: Clinical retrieval
# ──────────────────────────────────────────────────────────────────────────────

def _query_chroma(
    query: str,
    where: Optional[dict],
    top_k: int,
    distance_threshold: float,
) -> List[tuple[LilyChunk, float]]:
    """Returns list of (chunk, distance) sorted by distance ascending."""
    col = _get_collection()
    res = col.query(
        query_texts=[query],
        n_results=top_k,
        where=where if where else None,
        include=["documents", "metadatas", "distances"],
    )

    out: List[tuple[LilyChunk, float]] = []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]
    for cid, doc, meta, dist in zip(ids, docs, metas, dists):
        if dist > distance_threshold:
            continue
        out.append((LilyChunk.from_chroma_result(cid, doc, meta), dist))
    return out


def retrieve_clinical(
    query: str,
    symptom_keywords: List[str] | None = None,
    gestational_context: str = "unknown",
    severity_signal: str = "none",
    top_k: int = 3,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> List[tuple[LilyChunk, float]]:
    """
    Severity is used as a re-ranking *bias*, not a hard filter. We retrieve
    a wider candidate pool and then promote escalate/monitor chunks to the
    top when severity is high. A hard filter would silently return zero
    results when the KB has no matching content for the symptom + tier.
    """
    candidates = _query_chroma(query, where=None, top_k=top_k * 3,
                                distance_threshold=distance_threshold)

    if severity_signal == "high":
        # Stable sort: escalate/monitor chunks rise to the top, ties broken by distance
        priority = {"escalate": 0, "monitor": 1}
        candidates.sort(key=lambda cd: (priority.get(cd[0].action_type, 2), cd[1]))

    return candidates[:top_k]


def retrieve_emotional(
    query: str,
    top_k: int = 3,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> List[tuple[LilyChunk, float]]:
    """
    Emotional turns (anxiety, sadness, suicidal ideation) need to retrieve
    from postpartum mental-health content. We don't filter — the KB chunks
    for these scenarios are tagged action_type=escalate/monitor with mood
    symptom_tags, and good semantic match handles the rest.
    """
    return _query_chroma(query, where=None, top_k=top_k,
                          distance_threshold=distance_threshold)


def retrieve_navigational(
    query: str,
    top_k: int = 3,
    distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
) -> List[tuple[LilyChunk, float]]:
    return _query_chroma(
        query,
        where={"action_type": "navigate"},
        top_k=top_k,
        distance_threshold=distance_threshold,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Prompt assembly
# ──────────────────────────────────────────────────────────────────────────────

CLINICAL_REASONING_BLOCK = """\
[STRUCTURED REASONING — DO NOT SHOW THIS TO MARIA]
Before generating your response:
1. Identify the symptom or concern from what Maria just said
2. Check it against the retrieved context above
3. Consider her gestational stage and recent history
4. Determine the appropriate action_type: reassure / self_care / monitor / escalate
5. Then respond — warm, clear, with urgency proportional to the action_type
"""

EMOTIONAL_BLOCK = """\
[EMOTIONAL SUPPORT MODE]
Maria is expressing emotional distress. Acknowledge what she's feeling
before any clinical content. Name the emotion. Do not jump to logistics.
"""


def build_addendum(
    classification: Classification,
    retrieved_chunks: List[tuple[LilyChunk, float]],
) -> str:
    """
    Build ONLY the RAG-specific block(s) that should be appended to the
    caller's existing system prompt:

        [RETRIEVED MEDICAL CONTEXT]
        ---
        ...chunk text...
        Source: ... | action_type: ... | similarity: ...
        ---

        [STRUCTURED REASONING]   (clinical turns only)
        ...

        [EMOTIONAL SUPPORT MODE] (emotional turns only)
        ...

    Returns "" if there are no chunks AND no reasoning block to add — the
    caller can use that to skip RAG injection entirely on small-talk turns.
    """
    parts: List[str] = []

    if retrieved_chunks:
        parts.append("[RETRIEVED MEDICAL CONTEXT]")
        parts.append(
            "The following is retrieved from authoritative maternal health "
            "sources. Use it to inform your response. Do not quote it directly. "
            "Do not tell the patient you retrieved it. Speak as if you know this."
        )
        for chunk, dist in retrieved_chunks:
            parts.append("---")
            parts.append(chunk.text)
            parts.append(
                f"Source: {chunk.source} — {chunk.subtopic}"
                f"  |  action_type: {chunk.action_type}"
                f"  |  similarity: {1 - dist:.2f}"
            )
        parts.append("---")

    if classification.is_clinical:
        if parts:
            parts.append("")
        parts.append(CLINICAL_REASONING_BLOCK.strip())
    elif classification.is_emotional:
        if parts:
            parts.append("")
        parts.append(EMOTIONAL_BLOCK.strip())

    return "\n".join(parts)


def assemble_prompt(
    base_system_prompt: str,
    user_text: str,
    classification: Classification,
    retrieved_chunks: List[tuple[LilyChunk, float]],
    patient_context_block: str = "",
    history_block: str = "",
) -> str:
    """
    Build the full system prompt for standalone testing — base prompt plus
    addendum plus patient context plus history. Production callers should
    use `build_addendum()` and append it to whatever they already have.
    """
    parts = [base_system_prompt.strip()] if base_system_prompt else []

    addendum = build_addendum(classification, retrieved_chunks)
    if addendum:
        parts.append("\n" + addendum)

    if patient_context_block:
        parts.append("\n[PATIENT CONTEXT]")
        parts.append(patient_context_block.strip())

    if history_block:
        parts.append("\n[CONVERSATION HISTORY]")
        parts.append(history_block.strip())

    parts.append("\n[USER MESSAGE]")
    parts.append(user_text.strip())

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# One-shot orchestrator
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RAGResult:
    classification: Classification
    chunks: List[tuple[LilyChunk, float]]
    addendum: str              # ONLY the [RETRIEVED MEDICAL CONTEXT] + reasoning blocks
    full_prompt: str           # whole thing including base system prompt + history (for standalone tests)
    action_types_retrieved: List[str]   # for the rules engine to consume

    @property
    def has_context(self) -> bool:
        """True if any chunks were retrieved AND a reasoning block was built."""
        return bool(self.chunks) or self.classification.is_emotional


async def rag_for_turn(
    user_text: str,
    base_system_prompt: str = "",
    patient_context_block: str = "",
    history_block: str = "",
    top_k: int = 3,
) -> RAGResult:
    """
    Single async entry point. Classifies, retrieves (or skips), and assembles
    the prompt addendum. The caller appends `prompt_addendum` to whatever
    system prompt they're already building.
    """
    # Run classification — that's the only call that needs Claude. Embedding
    # of the query happens implicitly inside Chroma's collection.query().
    cls = await classify_turn_async(user_text)

    chunks: List[tuple[LilyChunk, float]] = []

    if cls.is_clinical:
        clinical = await asyncio.to_thread(
            retrieve_clinical,
            user_text,
            cls.symptom_keywords,
            cls.gestational_context,
            cls.severity_signal,
            top_k,
        )
        chunks.extend(clinical)

    if cls.is_navigational:
        nav = await asyncio.to_thread(
            retrieve_navigational, user_text, top_k,
        )
        chunks.extend(nav)

    if cls.is_emotional and not chunks:
        # Pure emotional turns still need retrieval — PPD/suicidal queries
        # depend on retrieving the right mental-health chunks.
        emo = await asyncio.to_thread(retrieve_emotional, user_text, top_k)
        chunks.extend(emo)

    # Deduplicate by chunk id, preserving order (lower distance first)
    seen = set()
    deduped: List[tuple[LilyChunk, float]] = []
    for c, d in sorted(chunks, key=lambda cd: cd[1]):
        if c.id in seen:
            continue
        seen.add(c.id)
        deduped.append((c, d))
    deduped = deduped[:top_k]

    addendum = build_addendum(cls, deduped)
    full = assemble_prompt(
        base_system_prompt=base_system_prompt,
        user_text=user_text,
        classification=cls,
        retrieved_chunks=deduped,
        patient_context_block=patient_context_block,
        history_block=history_block,
    )

    return RAGResult(
        classification=cls,
        chunks=deduped,
        addendum=addendum,
        full_prompt=full,
        action_types_retrieved=[c.action_type for c, _ in deduped],
    )
