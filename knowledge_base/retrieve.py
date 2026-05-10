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
# similar. With cosine, distance = 1 - similarity. 0.5 = similarity 0.5.
# For the PoC, accept anything under 0.6 (sim >= 0.4) — tune after testing.
DEFAULT_DISTANCE_THRESHOLD = 0.6

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
    where: dict = {}
    # Bias toward escalation chunks when severity is high
    if severity_signal == "high":
        where["action_type"] = {"$in": ["escalate", "monitor"]}

    # NOTE: We intentionally do NOT filter by gestational_relevance because
    # ChromaDB metadata is flat strings (we comma-joined the list). A naive
    # equality match would fail. The classifier's gestational hint is used
    # in prompt assembly, not retrieval, for the PoC.

    return _query_chroma(query, where, top_k, distance_threshold)


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


def assemble_prompt(
    base_system_prompt: str,
    user_text: str,
    classification: Classification,
    retrieved_chunks: List[tuple[LilyChunk, float]],
    patient_context_block: str = "",
    history_block: str = "",
) -> str:
    """
    Assemble the final system-prompt string for Claude.

    The exact ordering matches the spec in CLAUDE.md.
    Patient context + history are passed in by the caller (your friend's
    ConversationSession layer already builds these — pass them through).
    """
    parts = [base_system_prompt.strip()]

    # Retrieved medical context
    if retrieved_chunks:
        parts.append("\n[RETRIEVED MEDICAL CONTEXT]")
        parts.append(
            "The following is retrieved from authoritative maternal health "
            "sources. Use it to inform your response. Do not quote it directly. "
            "Do not tell Maria you retrieved it. Speak as if you know this."
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

    # Patient context (caller-supplied)
    if patient_context_block:
        parts.append("\n[PATIENT CONTEXT]")
        parts.append(patient_context_block.strip())

    # Reasoning instruction — clinical OR emotional
    if classification.is_clinical:
        parts.append("\n" + CLINICAL_REASONING_BLOCK.strip())
    elif classification.is_emotional:
        parts.append("\n" + EMOTIONAL_BLOCK.strip())

    if history_block:
        parts.append("\n[CONVERSATION HISTORY]")
        parts.append(history_block.strip())

    parts.append("\n[MARIA'S MESSAGE]")
    parts.append(user_text.strip())

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# One-shot orchestrator
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RAGResult:
    classification: Classification
    chunks: List[tuple[LilyChunk, float]]
    prompt_addendum: str       # the retrieved-context + reasoning block
    action_types_retrieved: List[str]   # for the rules engine to consume


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

    # Deduplicate by chunk id, preserving order (lower distance first)
    seen = set()
    deduped: List[tuple[LilyChunk, float]] = []
    for c, d in sorted(chunks, key=lambda cd: cd[1]):
        if c.id in seen:
            continue
        seen.add(c.id)
        deduped.append((c, d))
    deduped = deduped[:top_k]

    addendum = assemble_prompt(
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
        prompt_addendum=addendum,
        action_types_retrieved=[c.action_type for c, _ in deduped],
    )
