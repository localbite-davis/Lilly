"""
End-to-end ingestion pipeline for Lily's RAG knowledge base.

Flow:
    1. Scrape MedlinePlus topic pages (HTML)
    2. Scrape ACOG FAQ pages (HTML) + process any PDFs in raw/acog/
    3. Chunk all sources with paragraph-aware splitter (200-400 tokens)
    4. Heuristically classify metadata (action_type, tier_signal, etc.)
    5. Save chunks as JSON to /chunks/ for human review + git
    6. Upsert into ChromaDB at /chroma_db/ (uses default sentence-transformers
       embedding model — no API key needed)
    7. Print summary

Usage:
    python knowledge_base/ingest.py                # full ingestion
    python knowledge_base/ingest.py --skip-fetch   # skip network, use cached raw/

Notes:
    - Network calls are cached to /raw/ so re-running doesn't re-scrape.
    - ChromaDB's default embedding function is sentence-transformers
      (all-MiniLM-L6-v2 via ONNX). No OPENAI_API_KEY required.
    - Place ACOG PDFs in /raw/acog/ if you want to ingest those too. The
      scraper already grabs the FAQ pages so PDFs are optional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import List, Tuple

import requests
from bs4 import BeautifulSoup

import chromadb

# Local import — schema in same package
sys.path.insert(0, str(Path(__file__).parent))
from schema import LilyChunk  # noqa: E402
from seed_content import SEED_CHUNKS  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────

KB_DIR = Path(__file__).parent
RAW_DIR = KB_DIR / "raw"
ACOG_RAW = RAW_DIR / "acog"
MEDLINE_RAW = RAW_DIR / "medlineplus"
CHUNKS_DIR = KB_DIR / "chunks"
CHROMA_DIR = KB_DIR / "chroma_db"

for d in (ACOG_RAW, MEDLINE_RAW, CHUNKS_DIR, CHROMA_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────────────
# Sources to scrape
# ──────────────────────────────────────────────────────────────────────────────

# MedlinePlus topic pages — public, stable URLs.
MEDLINEPLUS_TOPICS = {
    "pregnancy": "https://medlineplus.gov/pregnancy.html",
    "prenatalcare": "https://medlineplus.gov/prenatalcare.html",
    "postpartumcare": "https://medlineplus.gov/postpartumcare.html",
    "highbloodpressureinpregnancy": "https://medlineplus.gov/highbloodpressureinpregnancy.html",
    "postpartumdepression": "https://medlineplus.gov/postpartumdepression.html",
    "breastfeeding": "https://medlineplus.gov/breastfeeding.html",
    "infantandnewborncare": "https://medlineplus.gov/infantandnewborncare.html",
    "childbirth": "https://medlineplus.gov/childbirth.html",
    "miscarriage": "https://medlineplus.gov/miscarriage.html",
    "diabetesandpregnancy": "https://medlineplus.gov/diabetesandpregnancy.html",
    "pregnancyandmedicines": "https://medlineplus.gov/pregnancyandmedicines.html",
}

# ACOG FAQ pages are JavaScript-rendered (Expand-All accordion components).
# BeautifulSoup can't see the actual Q&A content, so scraping returns page
# chrome ("Frequently Asked Questions", "Expand All", etc.). We rely on
# hand-curated SEED_CHUNKS (seed_content.py) to cover ACOG content. Leaving
# the dict empty here. To add ACOG via Playwright in the future, populate
# this dict and write a separate render-then-parse fetcher.
ACOG_FAQS: dict[str, str] = {}
ACOG_CURATED: dict[str, str] = {}

# Headings that are page chrome / nav cruft, not real subtopics.
NOISE_HEADINGS = {
    "expand all", "frequently asked questions", "summary", "topic image",
    "resources and glossary", "share this page", "see, play and learn",
    "research", "clinical trials", "learn more", "related issues",
}


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Lily-RAG-Ingestion) educational/non-commercial",
}


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 + 2: fetch sources (with on-disk cache)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch(url: str, cache_path: Path, force: bool = False) -> str:
    if cache_path.exists() and not force:
        return cache_path.read_text(encoding="utf-8")
    print(f"  GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    cache_path.write_text(r.text, encoding="utf-8")
    time.sleep(0.5)  # be nice
    return r.text


def fetch_all(skip_fetch: bool = False) -> List[Tuple[str, str, str, str]]:
    """
    Returns: list of (source, slug, url, html) tuples.
    Source is "MedlinePlus" or "ACOG".
    """
    out: List[Tuple[str, str, str, str]] = []

    print("Fetching MedlinePlus topics...")
    for slug, url in MEDLINEPLUS_TOPICS.items():
        cache = MEDLINE_RAW / f"{slug}.html"
        try:
            html = _fetch(url, cache, force=False) if not skip_fetch else (cache.read_text() if cache.exists() else "")
            if html:
                out.append(("MedlinePlus", slug, url, html))
        except Exception as e:
            print(f"  ! failed {slug}: {e}")

    print("\nFetching ACOG FAQ pages...")
    for slug, url in {**ACOG_FAQS, **ACOG_CURATED}.items():
        cache = ACOG_RAW / f"{slug}.html"
        try:
            html = _fetch(url, cache, force=False) if not skip_fetch else (cache.read_text() if cache.exists() else "")
            if html:
                out.append(("ACOG", slug, url, html))
        except Exception as e:
            print(f"  ! failed {slug}: {e}")

    return out


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: parse + chunk
# ──────────────────────────────────────────────────────────────────────────────

def html_to_paragraphs(html: str, source: str) -> List[Tuple[str, str]]:
    """
    Parse HTML and return a list of (heading, paragraph) pairs. Heading is
    the most recently seen <h2>/<h3> when the paragraph appears.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style/nav/footer chrome
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    # Pick a content root if we can find one (different per site)
    root = (
        soup.find("article")
        or soup.find("main")
        or soup.find(id="topic-summary")
        or soup.find(class_="content")
        or soup.body
        or soup
    )

    out: List[Tuple[str, str]] = []
    current_heading = ""
    for el in root.descendants:
        name = getattr(el, "name", None)
        if name in ("h1", "h2", "h3", "h4"):
            heading_text = el.get_text(" ", strip=True)
            # Skip page-chrome/nav headings; keep prior real heading instead.
            if heading_text.lower().strip() not in NOISE_HEADINGS:
                current_heading = heading_text
        elif name in ("p", "li"):
            text = el.get_text(" ", strip=True)
            text = re.sub(r"\s+", " ", text)
            if len(text) > 30:  # skip tiny fragments
                out.append((current_heading, text))
    return out


def _approx_tokens(text: str) -> int:
    # Rough heuristic — 4 chars per token. Good enough for chunk sizing.
    return max(1, len(text) // 4)


def chunk_paragraphs(
    paragraphs: List[Tuple[str, str]],
    target_tokens: int = 300,
    max_tokens: int = 500,
) -> List[Tuple[str, str]]:
    """
    Group consecutive (heading, paragraph) pairs into chunks of roughly
    target_tokens tokens, never exceeding max_tokens. Returns list of
    (heading, chunked_text).
    """
    chunks: List[Tuple[str, str]] = []
    cur_heading = ""
    cur_text: List[str] = []
    cur_tokens = 0

    def flush():
        nonlocal cur_text, cur_tokens
        if cur_text:
            chunks.append((cur_heading, " ".join(cur_text).strip()))
            cur_text = []
            cur_tokens = 0

    for heading, para in paragraphs:
        para_tokens = _approx_tokens(para)

        # New heading → flush before starting a new chunk
        if heading != cur_heading and cur_text:
            flush()
            cur_heading = heading

        if not cur_heading:
            cur_heading = heading

        if cur_tokens + para_tokens > max_tokens:
            flush()
            cur_heading = heading

        cur_text.append(para)
        cur_tokens += para_tokens

        if cur_tokens >= target_tokens:
            flush()

    flush()
    return chunks


# ──────────────────────────────────────────────────────────────────────────────
# Step 4: heuristic metadata classifier
# ──────────────────────────────────────────────────────────────────────────────

# Keywords are matched case-insensitively against chunk text + heading.

ESCALATE_KEYWORDS = [
    "warning sign", "warning signs", "emergency", "call 911", "go to the emergency",
    "go to the hospital", "seek emergency", "severe headache", "severe pain",
    "vision changes", "seeing spots", "blurred vision", "stroke",
    "seizure", "convulsion", "chest pain", "trouble breathing", "shortness of breath",
    "heavy bleeding", "soaking a pad", "more than a pad an hour", "soaks a pad",
    "preeclampsia", "eclampsia", "hellp", "thoughts of harm", "harm yourself",
    "hurt the baby", "suicide", "suicidal", "no longer want to live",
    "unable to keep food down", "fever above", "high fever",
]

MONITOR_KEYWORDS = [
    "monitor", "track", "watch for", "if it gets worse", "call your provider if",
    "contact your doctor if", "if symptoms persist", "still bleeding", "lochia",
    "follow up", "check your", "keep an eye",
]

NAVIGATE_KEYWORDS = [
    "wic", "medicaid", "insurance", "appointment", "schedule a", "transportation",
    "support program", "resources", "211", "snap benefits", "benefits", "enrollment",
    "find a provider", "find a clinic",
]

SELF_CARE_KEYWORDS = [
    "rest", "stay hydrated", "drink water", "drink fluids", "small frequent meals",
    "ginger", "saltines", "elevate your", "ice pack", "warm compress", "kegel",
    "lactation", "latch", "nipple", "milk supply", "self-care", "at home",
    "comfort measure",
]

EMOTIONAL_KEYWORDS = [
    "depression", "anxiety", "feeling sad", "mood", "baby blues", "postpartum mood",
    "isolated", "overwhelmed",
]

GESTATIONAL_KEYWORDS = {
    "T1": ["first trimester", "early pregnancy", "weeks 1-12", "first 12 weeks"],
    "T2": ["second trimester", "weeks 13", "weeks 14", "weeks 15", "weeks 16",
           "weeks 17", "weeks 18", "weeks 19", "weeks 20", "weeks 21", "weeks 22",
           "weeks 23", "weeks 24", "weeks 25", "weeks 26", "weeks 27"],
    "T3": ["third trimester", "weeks 28", "weeks 29", "weeks 30", "weeks 31",
           "weeks 32", "weeks 33", "weeks 34", "weeks 35", "weeks 36", "weeks 37",
           "weeks 38", "weeks 39", "weeks 40", "near delivery", "near term"],
    "postpartum_early": ["postpartum", "after birth", "after delivery",
                          "first six weeks", "first 6 weeks", "lochia"],
    "postpartum_late": ["postpartum depression", "postpartum mood",
                         "first year postpartum", "after the first 6 weeks"],
    "newborn": ["newborn", "baby", "infant", "breastfeeding", "latch",
                "umbilical", "diaper"],
}

SYMPTOM_KEYWORDS = [
    "headache", "edema", "swelling", "bleeding", "spotting", "cramping",
    "nausea", "vomiting", "fatigue", "back pain", "pelvic pain",
    "contractions", "fetal movement", "kick count", "blood pressure",
    "fever", "depression", "anxiety", "mood", "latch", "nipple pain",
    "shortness of breath", "chest pain", "vision changes", "dizzy",
    "lightheaded", "seizure", "leg pain", "swollen leg", "calf pain",
]


def classify(text: str, heading: str, source: str, slug: str) -> dict:
    """Heuristically derive metadata fields from chunk content."""
    blob = (text + " " + heading).lower()

    # Special-case: ACOG urgent warning signs page is always escalate/hand_off
    if "urgent-maternal-warning-signs" in slug or "warning sign" in heading.lower():
        action_type = "escalate"
        tier_signal = "hand_off"
        severity = "high"
    elif any(kw in blob for kw in ESCALATE_KEYWORDS):
        action_type = "escalate"
        # Mental-health escalations route to hand_up (volunteer doctor),
        # bleeding/seizure/stroke route to hand_off (911).
        if any(kw in blob for kw in ["suicide", "suicidal", "harm yourself", "thoughts of harm"]):
            tier_signal = "hand_up"
            severity = "high"
        else:
            tier_signal = "hand_off"
            severity = "high"
    elif any(kw in blob for kw in NAVIGATE_KEYWORDS):
        action_type = "navigate"
        tier_signal = "none"
        severity = "low"
    elif any(kw in blob for kw in MONITOR_KEYWORDS):
        action_type = "monitor"
        # Postpartum bleeding monitoring → hand_up (provider review)
        if "bleed" in blob or "lochia" in blob:
            tier_signal = "hand_up"
            severity = "medium"
        else:
            tier_signal = "handle"
            severity = "medium"
    elif any(kw in blob for kw in EMOTIONAL_KEYWORDS):
        action_type = "monitor"
        tier_signal = "hand_up"
        severity = "medium"
    elif any(kw in blob for kw in SELF_CARE_KEYWORDS):
        action_type = "self_care"
        tier_signal = "handle"
        severity = "low"
    else:
        action_type = "reassure"
        tier_signal = "handle"
        severity = "low"

    # Gestational relevance — multi-stage match
    gestational: List[str] = []
    for stage, kws in GESTATIONAL_KEYWORDS.items():
        if any(kw in blob for kw in kws):
            gestational.append(stage)
    # Default: if it's "pregnancy" content with no specific stage, mark all trimesters.
    if not gestational:
        if "pregnan" in blob:
            gestational = ["T1", "T2", "T3"]
        elif "postpartum" in blob or "after birth" in blob:
            gestational = ["postpartum_early", "postpartum_late"]
        elif "newborn" in blob or "infant" in blob or "breastfeed" in blob:
            gestational = ["newborn"]

    # Symptom tags — collect any matches
    tags = sorted({s for s in SYMPTOM_KEYWORDS if s in blob})

    return {
        "action_type": action_type,
        "tier_signal": tier_signal,
        "severity": severity,
        "gestational_relevance": gestational,
        "symptom_tags": tags,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Optional: ACOG PDFs in raw/acog/
# ──────────────────────────────────────────────────────────────────────────────

def load_acog_pdfs() -> List[Tuple[str, str, str, str]]:
    """Returns list of (source='ACOG', slug, source_url=filename, raw_text)."""
    out = []
    pdfs = list(ACOG_RAW.glob("*.pdf"))
    if not pdfs:
        return out
    print(f"\nLoading {len(pdfs)} ACOG PDFs from {ACOG_RAW}...")
    try:
        import fitz  # pymupdf
    except ImportError:
        print("  ! pymupdf not installed — skipping PDFs (run: pip install pymupdf)")
        return out
    for pdf_path in pdfs:
        try:
            doc = fitz.open(pdf_path)
            text = "\n\n".join(page.get_text() for page in doc)
            doc.close()
            slug = pdf_path.stem
            out.append(("ACOG", slug, pdf_path.name, text))
            print(f"  loaded {pdf_path.name} ({len(text)} chars)")
        except Exception as e:
            print(f"  ! failed {pdf_path.name}: {e}")
    return out


def pdf_text_to_paragraphs(text: str) -> List[Tuple[str, str]]:
    """Rudimentary heading detection for PDFs — lines in ALL CAPS or short
    title-cased lines become headings."""
    out: List[Tuple[str, str]] = []
    current_heading = ""
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        # Heuristic heading: short, mostly capitalized, no period at end
        if len(block) < 80 and not block.endswith(".") and (
            block.isupper() or sum(1 for w in block.split() if w[:1].isupper()) >= len(block.split()) * 0.6
        ):
            current_heading = block
            continue
        out.append((current_heading, re.sub(r"\s+", " ", block)))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Step 5+6+7: build chunks → save JSON → embed → upsert into Chroma
# ──────────────────────────────────────────────────────────────────────────────

def _chunk_id(source: str, slug: str, idx: int, text: str) -> str:
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{source.lower()}-{slug}-{idx:03d}-{h}"


def build_chunks(sources: List[Tuple[str, str, str, str]], from_pdf: bool = False) -> List[LilyChunk]:
    chunks: List[LilyChunk] = []
    for source, slug, source_url, raw in sources:
        if from_pdf:
            paragraphs = pdf_text_to_paragraphs(raw)
        else:
            paragraphs = html_to_paragraphs(raw, source)

        if not paragraphs:
            print(f"  no paragraphs extracted from {slug}")
            continue

        for idx, (heading, body) in enumerate(chunk_paragraphs(paragraphs)):
            meta = classify(body, heading, source, slug)
            topic = slug.replace("-", " ").replace("_", " ")
            subtopic = heading or topic
            chunk = LilyChunk(
                id=_chunk_id(source, slug, idx, body),
                text=body,
                source=source,
                source_url=source_url,
                topic=topic,
                subtopic=subtopic,
                gestational_relevance=meta["gestational_relevance"],
                action_type=meta["action_type"],
                tier_signal=meta["tier_signal"],
                severity=meta["severity"],
                symptom_tags=meta["symptom_tags"],
                plain_language=True,
                last_verified=str(time.localtime().tm_year),
            )
            chunks.append(chunk)
    return chunks


def save_chunks_json(chunks: List[LilyChunk]):
    # Group by source/slug for easier human review
    grouped: dict[str, List[dict]] = {}
    for c in chunks:
        key = f"{c.source.lower()}_{c.topic.replace(' ', '-')}"
        grouped.setdefault(key, []).append(c.to_dict())
    for key, items in grouped.items():
        path = CHUNKS_DIR / f"{key}.json"
        path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  saved {len(chunks)} chunks across {len(grouped)} files in {CHUNKS_DIR}")


def upsert_chroma(chunks: List[LilyChunk]):
    print(f"\nUpserting {len(chunks)} chunks into ChromaDB at {CHROMA_DIR}...")
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Default embedding function = sentence-transformers all-MiniLM-L6-v2 (ONNX)
    collection = client.get_or_create_collection(
        name="lily_medical",
        metadata={"hnsw:space": "cosine"},
    )
    # Batch upsert in groups of 100 to stay friendly with embedding compute
    BATCH = 100
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            metadatas=[c.to_chroma_metadata() for c in batch],
        )
        print(f"  upserted {min(i + BATCH, len(chunks))}/{len(chunks)}")
    print(f"\nCollection size: {collection.count()}")


# ──────────────────────────────────────────────────────────────────────────────
# Step 8: summary
# ──────────────────────────────────────────────────────────────────────────────

def print_summary(chunks: List[LilyChunk]):
    by_source: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    for c in chunks:
        by_source[c.source] = by_source.get(c.source, 0) + 1
        by_action[c.action_type] = by_action.get(c.action_type, 0) + 1
        by_tier[c.tier_signal] = by_tier.get(c.tier_signal, 0) + 1

    print("\n" + "=" * 60)
    print("INGESTION SUMMARY")
    print("=" * 60)
    print(f"Total chunks: {len(chunks)}")
    print("\nBy source:")
    for s, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {s:15s} {n}")
    print("\nBy action_type:")
    for a, n in sorted(by_action.items(), key=lambda x: -x[1]):
        print(f"  {a:15s} {n}")
    print("\nBy tier_signal:")
    for t, n in sorted(by_tier.items(), key=lambda x: -x[1]):
        print(f"  {t:15s} {n}")
    print("=" * 60)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Ingest Lily's RAG knowledge base")
    ap.add_argument("--skip-fetch", action="store_true",
                     help="use cached HTML in raw/, skip network calls")
    args = ap.parse_args()

    # Step 1+2: fetch
    html_sources = fetch_all(skip_fetch=args.skip_fetch)
    print(f"\nFetched {len(html_sources)} HTML pages.")

    # Optional PDFs
    pdf_sources = load_acog_pdfs()

    # Step 3+4: chunk + classify
    print("\nChunking + classifying...")
    chunks = build_chunks(html_sources, from_pdf=False)
    if pdf_sources:
        chunks += build_chunks(pdf_sources, from_pdf=True)
    print(f"  produced {len(chunks)} scraped chunks")

    # Add hand-curated authoritative seed chunks (cover scenarios where
    # automated scraping fails — ACOG FAQs, PSI postpartum mental health, etc.)
    print(f"  adding {len(SEED_CHUNKS)} hand-curated seed chunks")
    chunks += list(SEED_CHUNKS)

    if not chunks:
        print("No chunks produced — aborting before Chroma upsert.")
        return

    # Step 5: save JSON
    print("\nSaving chunks as JSON...")
    save_chunks_json(chunks)

    # Step 6+7: upsert into ChromaDB
    upsert_chroma(chunks)

    # Step 8: summary
    print_summary(chunks)


if __name__ == "__main__":
    main()
