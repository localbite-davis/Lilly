# Lily RAG Knowledge Base

Grounds Claude's responses in authoritative maternal-health content
(MedlinePlus + ACOG). Sits between STT output and the Claude API call.

## Layout

```
knowledge_base/
  schema.py          LilyChunk dataclass — every chunk's metadata schema
  ingest.py          Scrape → chunk → classify → embed → Chroma upsert (run once)
  retrieve.py        Classify → retrieve → assemble prompt addendum (called at runtime)
  test_retrieval.py  8 test queries — must all pass before wiring into voice pipeline
  requirements.txt   Extra deps (also added to root requirements.txt)
  raw/
    medlineplus/     Cached MedlinePlus HTML (auto-fetched by ingest.py)
    acog/            Cached ACOG HTML + optional PDFs you drop here
  chunks/            Processed chunks as JSON (committed for review)
  chroma_db/         Persisted Chroma vector store (committed)
```

## How to ingest (one person runs this; everyone else just pulls)

```bash
# from repo root, with .venv activated
pip install -r knowledge_base/requirements.txt
python knowledge_base/ingest.py

# Then commit the artifacts so teammates don't need to re-ingest:
git add knowledge_base/chunks/ knowledge_base/chroma_db/
git commit -m "kb: rebuild chunks + chroma store"
```

The default embedding model is `sentence-transformers/all-MiniLM-L6-v2`
(via ChromaDB's default ONNX runner). No API key required for embeddings.

## How to validate

```bash
python knowledge_base/test_retrieval.py
```

All 8 test cases must pass with the right `action_type` and `tier_signal`.
A failing case means the chunks for that topic aren't good enough — fix
the ingestion (better source page, better classifier rules) before
trusting retrieval downstream.

## How to use from the voice pipeline (later)

```python
from knowledge_base.retrieve import rag_for_turn

result = await rag_for_turn(
    user_text=transcript,
    base_system_prompt=LILY_STATIC_SYSTEM_PROMPT,
    patient_context_block=patient_block,
    history_block=last_3_turns,
)
# result.prompt_addendum → feed to Claude as the system prompt
# result.action_types_retrieved → flag to rules engine for cross-check
```

The rules engine still owns the final triage classification.
RAG informs Claude's response *quality*, not the escalation decision.

## Sources covered (PoC)

**MedlinePlus** (auto-scraped):
pregnancy, prenatal care, postpartum care, high BP in pregnancy,
postpartum depression, breastfeeding, infant + newborn care, childbirth,
miscarriage, diabetes & pregnancy, pregnancy + medicines.

**ACOG FAQs** (auto-scraped, free, patient-facing):
preeclampsia, postpartum depression, bleeding during pregnancy,
nutrition, postpartum pain management, breastfeeding, early pregnancy
loss, morning sickness, exercise, gestational diabetes, depression
resources, urgent maternal warning signs.

**ACOG PDFs** (optional, manual):
Drop any extra PDFs in `raw/acog/`. They'll be picked up automatically.

## Direct links if you want extra ACOG PDFs

These are the patient-facing PDFs we don't already scrape via FAQ pages.
Drop them in `raw/acog/` if you want extra coverage:

- Urgent Maternal Warning Signs (the one-page infographic):
  https://www.acog.org/-/media/project/acog/acogorg/files/forms/patients/urgent-maternal-warning-signs.pdf
- Patient FAQ booklet PDFs are not consistently published as PDFs anymore —
  the FAQ scrape covers the same content.
