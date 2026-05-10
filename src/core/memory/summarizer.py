"""
Post-call summarizer — uses Claude to generate a 2–3 sentence narrative of
each call, then stores it in both PostgreSQL (conversations.summary) and
Pinecone (for semantic retrieval at future call start).

Called by the session after end_session is invoked.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger(__name__)

_SUMMARIZER_PROMPT = """\
You are a clinical note-writer for Lily, a maternal health phone companion.
Summarize the following conversation transcript in 2–3 plain English sentences.
Focus on: symptoms reported, vitals given, triage outcome, and any follow-up needed.
Do NOT include the patient's name or phone number.
Do NOT use clinical jargon the patient wouldn't understand.
Write in past tense, third person ("The caller reported...").

Transcript:
{transcript}

Symptoms logged: {symptoms}
Vitals: {vitals}
Triage tier: {tier}
"""


async def summarize_call(
    transcript: str,
    symptoms: list[str],
    vitals: dict,
    tier: str,
) -> str:
    """
    Generate a post-call summary using Claude.
    Returns a fallback string if the API is unavailable.
    """
    from src.config import settings

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        prompt = _SUMMARIZER_PROMPT.format(
            transcript=transcript[:3000],  # cap to avoid token blowout
            symptoms=", ".join(symptoms) if symptoms else "none reported",
            vitals=str(vitals) if vitals else "none",
            tier=tier,
        )
        response = await client.messages.create(
            model=settings.lily_model_fallback,  # use Haiku for cost efficiency
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text.strip()
        log.info("call_summary_generated", tier=tier, chars=len(summary))
        return summary
    except Exception as exc:
        log.warning("summarizer_failed", exc_info=exc)
        symptoms_str = ", ".join(symptoms) if symptoms else "no symptoms"
        return f"Caller reported {symptoms_str}. Triage outcome: {tier}."


async def save_call_summary(
    patient_id: int,
    conversation_id: int,
    summary: str,
) -> None:
    """
    Persist summary to Pinecone for semantic retrieval at next call.
    PostgreSQL persistence is handled via end_conversation() in real_db.
    """
    try:
        from src.core.memory.vector_store import memory_store
        await memory_store.save_memory(
            patient_id=patient_id,
            text=summary,
            memory_type="call_summary",
        )
    except Exception as exc:
        log.warning("save_call_summary_pinecone_failed", patient_id=patient_id, exc_info=exc)
