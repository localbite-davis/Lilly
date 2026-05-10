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

## Test the full text → RAG → Claude → text loop (no audio)

```bash
# interactive REPL — type messages, watch Lily respond
python knowledge_base/text_chat.py
python knowledge_base/text_chat.py --debug   # also shows the RAG addendum injected

# scripted assertions — covers smalltalk-skips-RAG and clinical-uses-RAG cases
python knowledge_base/test_text_flow.py
python knowledge_base/test_text_flow.py -v   # also dump Lily's replies
```

## Wiring into ConversationSession

The integration contract is short: **only inject the RAG addendum on
clinical / navigational / emotional turns.** Smalltalk turns skip RAG so
we don't pay the ~150 ms classification + retrieval latency on greetings.

```python
from knowledge_base.retrieve import rag_for_turn

# Inside ConversationSession, right before building the system prompt
# for a Claude turn:
rag = await rag_for_turn(
    user_text=transcript,
    base_system_prompt="",                     # we only need the addendum here
)

if rag.has_context and rag.addendum:
    system_prompt = LILY_STATIC_SYSTEM_PROMPT + "\n\n" + rag.addendum
else:
    system_prompt = LILY_STATIC_SYSTEM_PROMPT  # smalltalk — skip RAG entirely

# Pass action_types_retrieved to the rules engine for cross-check
if "escalate" in rag.action_types_retrieved:
    rules_engine.flag_escalation_context(session_id)
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
