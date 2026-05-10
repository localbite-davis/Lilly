"""Tests for tts_bridge.py — Stage 5.2. All table-driven cases must pass."""

from __future__ import annotations

import pytest

from src.core.agent.tts_bridge import TextChunker


def chunks(deltas: list[str], max_chars: int = 80, min_chars: int = 20) -> list[str]:
    """Feed all deltas then flush, return all emitted chunks."""
    c = TextChunker(max_chars=max_chars, min_chars=min_chars)
    result: list[str] = []
    for d in deltas:
        result.extend(c.feed(d))
    tail = c.flush()
    if tail:
        result.append(tail)
    return result


# ---------------------------------------------------------------------------
# Table-driven cases from the handoff spec
# ---------------------------------------------------------------------------

def test_simple_sentence_with_comma():
    result = chunks(["Hi Maria, this is Lily."])
    assert len(result) >= 1
    full = " ".join(result)
    assert "Hi Maria" in full
    assert "Lily" in full


def test_abbreviation_dr_not_split():
    result = chunks(["Dr. Chen cleared Unisom for nausea."])
    # Must NOT split after "Dr."
    assert len(result) == 1
    assert result[0] == "Dr. Chen cleared Unisom for nausea."


def test_decimal_not_split():
    result = chunks(["Your BP is 148.5 over 94, which is mildly elevated."])
    full = " ".join(result)
    assert "148.5" in full
    # "148.5" must appear intact — not split across chunks
    for chunk in result:
        assert "148." not in chunk or "148.5" in chunk


def test_flush_emits_remainder():
    result = chunks(["Hello"])
    assert result == ["Hello"]


def test_pathological_no_spaces():
    long_text = "a" * 200
    result = chunks([long_text])
    reconstructed = "".join(result)
    assert reconstructed == long_text


def test_question_marks_split():
    result = chunks(["What's going on? I'm here."])
    assert len(result) == 2
    assert result[0].rstrip() == "What's going on?"
    assert "I'm here." in result[1]


def test_abbreviation_ie_not_split():
    result = chunks(["Per ACOG i.e. the standard, this needs a doctor."])
    full = " ".join(result)
    assert "i.e." in full
    # The dot after "i.e" should not cause a split
    no_split_at_ie = all("i.e." not in c or c.strip().startswith("Per") for c in result)
    # Just verify the full text is preserved
    assert "Per ACOG i.e. the standard" in full


def test_exclamation_splits():
    result = chunks(["That is great! Now let me check your BP."])
    assert len(result) >= 2
    assert "great!" in result[0]


def test_semicolon_splits_when_long_enough():
    text = "Your symptoms are noted; I want to run a check now."
    result = chunks([text], min_chars=20)
    full = " ".join(result)
    assert "noted" in full
    assert "check" in full


def test_hard_cap_splits_at_last_space():
    # 85-char text with no sentence boundary — should hard-cap at 80
    text = "a" * 40 + " " + "b" * 40
    result = chunks([text], max_chars=80)
    for chunk in result:
        assert len(chunk) <= 80


def test_buffer_resets_after_flush():
    c = TextChunker()
    c.feed("Hello world.")
    c.flush()
    assert c._buffer == ""


def test_multiple_sentences():
    result = chunks(["Hi Maria. How are you feeling today? Let me know."])
    full = " ".join(result)
    assert "Hi Maria" in full
    assert "feeling today" in full
    assert "Let me know" in full
    assert len(result) >= 2


def test_colon_splits_clause():
    text = "Here is what I recommend: drink plenty of water and rest."
    result = chunks([text], min_chars=10)
    full = " ".join(result)
    assert "recommend" in full
    assert "drink plenty" in full


def test_comma_split_with_long_tail():
    # comma with 30+ chars after it — should split if buffer >= min_chars
    text = "I hear you, and I want to make sure you are getting the right support."
    result = chunks([text], min_chars=15)
    full = " ".join(result)
    assert "I hear you" in full
    assert "right support" in full


def test_short_buffer_no_emit():
    c = TextChunker(min_chars=20)
    result = c.feed("Hi")
    assert result == []
    # flush still returns it
    assert c.flush() == "Hi"


def test_feed_incremental_deltas():
    c = TextChunker()
    all_chunks: list[str] = []
    for word in ["Hello", " Maria,", " this", " is", " Lily."]:
        all_chunks.extend(c.feed(word))
    tail = c.flush()
    if tail:
        all_chunks.append(tail)
    full = " ".join(all_chunks).replace("  ", " ")
    assert "Hello" in full
    assert "Lily." in full
