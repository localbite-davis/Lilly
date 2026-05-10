"""
Schema for a single chunk in Lily's RAG knowledge base.

Every chunk in the ChromaDB store is created from a `LilyChunk` instance.
The metadata fields drive retrieval filtering and downstream response
generation — `action_type` and `tier_signal` in particular are read by the
prompt assembler and (eventually) cross-referenced with the rules engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List


VALID_SOURCES = {"ACOG", "MedlinePlus", "CDC", "AAP", "PSI"}
VALID_ACTION_TYPES = {"reassure", "self_care", "monitor", "escalate", "navigate"}
VALID_TIER_SIGNALS = {"handle", "hand_up", "hand_off", "none"}
VALID_SEVERITIES = {"low", "medium", "high"}
VALID_GESTATIONAL = {"T1", "T2", "T3", "postpartum_early", "postpartum_late", "newborn"}


@dataclass
class LilyChunk:
    id: str                            # unique, e.g. "acog-preeclampsia-001"
    text: str                          # the actual clinical content
    source: str                        # "ACOG" | "MedlinePlus" | "CDC" | "AAP" | "PSI"
    source_url: str                    # original URL or filename
    topic: str                         # broad topic e.g. "hypertension"
    subtopic: str                      # specific e.g. "pre-eclampsia warning signs"
    gestational_relevance: List[str] = field(default_factory=list)
    action_type: str = "reassure"      # reassure | self_care | monitor | escalate | navigate
    tier_signal: str = "handle"        # handle | hand_up | hand_off | none
    severity: str = "low"              # low | medium | high
    symptom_tags: List[str] = field(default_factory=list)
    plain_language: bool = True        # True if patient-facing language
    last_verified: str = ""            # year as string e.g. "2024"

    def __post_init__(self):
        if self.source not in VALID_SOURCES:
            raise ValueError(f"invalid source: {self.source}")
        if self.action_type not in VALID_ACTION_TYPES:
            raise ValueError(f"invalid action_type: {self.action_type}")
        if self.tier_signal not in VALID_TIER_SIGNALS:
            raise ValueError(f"invalid tier_signal: {self.tier_signal}")
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"invalid severity: {self.severity}")
        for stage in self.gestational_relevance:
            if stage not in VALID_GESTATIONAL:
                raise ValueError(f"invalid gestational stage: {stage}")

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    def to_chroma_metadata(self) -> dict:
        """ChromaDB metadata must be flat (no lists/dicts), so we comma-join
        the list fields. The retrieval layer splits them back out."""
        return {
            "source": self.source,
            "source_url": self.source_url,
            "topic": self.topic,
            "subtopic": self.subtopic,
            "action_type": self.action_type,
            "tier_signal": self.tier_signal,
            "severity": self.severity,
            "symptom_tags": ",".join(self.symptom_tags),
            "gestational_relevance": ",".join(self.gestational_relevance),
            "plain_language": self.plain_language,
            "last_verified": self.last_verified,
        }

    @classmethod
    def from_chroma_result(cls, chunk_id: str, document: str, metadata: dict) -> "LilyChunk":
        """Rebuild a chunk from a ChromaDB query result."""
        return cls(
            id=chunk_id,
            text=document,
            source=metadata.get("source", "MedlinePlus"),
            source_url=metadata.get("source_url", ""),
            topic=metadata.get("topic", ""),
            subtopic=metadata.get("subtopic", ""),
            gestational_relevance=[s for s in metadata.get("gestational_relevance", "").split(",") if s],
            action_type=metadata.get("action_type", "reassure"),
            tier_signal=metadata.get("tier_signal", "handle"),
            severity=metadata.get("severity", "low"),
            symptom_tags=[s for s in metadata.get("symptom_tags", "").split(",") if s],
            plain_language=metadata.get("plain_language", True),
            last_verified=metadata.get("last_verified", ""),
        )
