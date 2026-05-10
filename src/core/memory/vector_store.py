"""
Pinecone vector store for Lily's long-term patient memory.

Stores call summaries, fears, preferences, and clinical notes as semantic
vectors. Used to populate PatientContext.recent_summaries at call start.

Requires:
  PINECONE_API_KEY — from .env
  OPENAI_API_KEY   — for text-embedding-3-small embeddings
"""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def _get_pinecone_index():
    """Lazy-initialize Pinecone index. Cached after first call."""
    from pinecone import Pinecone, ServerlessSpec
    from src.config import settings

    if not settings.pinecone_api_key:
        raise RuntimeError("PINECONE_API_KEY not set — cannot use vector store")

    pc = Pinecone(api_key=settings.pinecone_api_key)
    existing = [idx.name for idx in pc.list_indexes()]

    if settings.pinecone_index not in existing:
        pc.create_index(
            name=settings.pinecone_index,
            dimension=settings.openai_embedding_dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region=settings.pinecone_env),
        )
        log.info("pinecone_index_created", index=settings.pinecone_index)

    return pc.Index(settings.pinecone_index)


def _embed(text: str) -> list[float]:
    """Embed text using OpenAI text-embedding-3-small (sync)."""
    from openai import OpenAI
    from src.config import settings

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not set — cannot embed text")

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return response.data[0].embedding


class MemoryStore:
    """
    Async-friendly wrapper over Pinecone. Embedding calls are sync (OpenAI SDK
    doesn't have a native async client), so they run in an executor.
    """

    def __init__(self) -> None:
        self._index = None  # lazy init

    def _ensure_index(self):
        if self._index is None:
            self._index = _get_pinecone_index()
        return self._index

    async def save_memory(
        self,
        patient_id: int,
        text: str,
        memory_type: str = "call_summary",
    ) -> None:
        """Embed and upsert a memory vector for a patient."""
        loop = asyncio.get_event_loop()
        try:
            vector = await loop.run_in_executor(None, _embed, text)
            index = self._ensure_index()
            memory_id = f"pt_{patient_id}_{int(time.time())}"
            await loop.run_in_executor(
                None,
                lambda: index.upsert(vectors=[{
                    "id": memory_id,
                    "values": vector,
                    "metadata": {
                        "patient_id": patient_id,
                        "type": memory_type,
                        "text": text,
                    },
                }]),
            )
            log.info("memory_saved", patient_id=patient_id, type=memory_type)
        except Exception as exc:
            log.error("memory_save_failed", patient_id=patient_id, exc_info=exc)

    async def retrieve_relevant_context(
        self,
        patient_id: int,
        query: str,
        top_k: int = 3,
    ) -> list[str]:
        """
        Return the top_k most semantically relevant past memories for this patient.
        Returns an empty list if the API is unavailable or keys are missing.
        """
        loop = asyncio.get_event_loop()
        try:
            query_vector = await loop.run_in_executor(None, _embed, query)
            index = self._ensure_index()
            results = await loop.run_in_executor(
                None,
                lambda: index.query(
                    vector=query_vector,
                    filter={"patient_id": {"$eq": patient_id}},
                    top_k=top_k,
                    include_metadata=True,
                ),
            )
            return [m["metadata"]["text"] for m in results.get("matches", []) if m.get("metadata", {}).get("text")]
        except Exception as exc:
            log.warning("memory_retrieve_failed", patient_id=patient_id, exc_info=exc)
            return []

    async def retrieve_summaries(
        self,
        patient_id: int,
        top_k: int = 5,
    ) -> list[str]:
        """Return the top recent call summaries for populating PatientContext."""
        return await self.retrieve_relevant_context(
            patient_id=patient_id,
            query="patient history recent calls symptoms",
            top_k=top_k,
        )


# Module-level singleton — one per process
memory_store = MemoryStore()
