"""
TextChunker — buffers Claude text deltas and emits clause-sized chunks for ElevenLabs.

Splitting rules (in priority order):
  1. Sentence boundary: . ! ? followed by space+capital — unless preceded by an
     abbreviation or inside a decimal number.
  2. Strong clause: ; or : followed by space, if buffer >= min_chars.
  3. Comma clause: ", " followed by 30+ chars of tail, if buffer >= min_chars.
  4. Hard cap: buffer >= max_chars and has a space — split at last space <= max_chars.
  5. No fallback: emit nothing, wait for more deltas.
"""

from __future__ import annotations

import re

_ABBREVIATIONS = frozenset({
    "Dr", "Mr", "Mrs", "Ms", "St", "Ave", "Blvd", "Rd",
    "etc", "e.g", "i.e", "vs", "Jr", "Sr", "Prof", "Lt", "Sgt",
})

# Matches a sentence-ending punctuation followed by space and uppercase letter.
_SENTENCE_END_RE = re.compile(r'([.!?])\s+([A-Z])')

# Matches a decimal number (digits.digits) to avoid splitting inside it.
_DECIMAL_RE = re.compile(r'\d+\.\d')


def _ends_with_abbreviation(text: str, dot_pos: int) -> bool:
    """Return True if the character before position dot_pos is an abbreviation."""
    before = text[:dot_pos]
    word_match = re.search(r'([A-Za-z.]+)$', before)
    if not word_match:
        return False
    word = word_match.group(1).rstrip(".")
    return word in _ABBREVIATIONS


def _is_inside_decimal(text: str, dot_pos: int) -> bool:
    """Return True if dot_pos is inside a decimal number."""
    for m in _DECIMAL_RE.finditer(text):
        if m.start() <= dot_pos < m.end():
            return True
    return False


class TextChunker:
    """
    Buffer Claude text deltas and emit chunks sized for ElevenLabs streaming.

    Usage:
        chunker = TextChunker()
        for delta in claude_stream:
            for chunk in chunker.feed(delta):
                await tts.feed(chunk)
        tail = chunker.flush()
        if tail:
            await tts.feed(tail)
    """

    def __init__(self, max_chars: int = 80, min_chars: int = 20) -> None:
        self._buffer: str = ""
        self._max = max_chars
        self._min = min_chars

    def feed(self, delta: str) -> list[str]:
        """Append delta. Return zero or more chunks ready to send to TTS."""
        self._buffer += delta
        chunks: list[str] = []
        while True:
            chunk, remainder = self._extract_chunk()
            if chunk is None:
                break
            chunks.append(chunk)
            self._buffer = remainder
        return chunks

    def flush(self) -> str | None:
        """Called when Claude's turn ends. Returns whatever's left."""
        if self._buffer.strip():
            out = self._buffer
            self._buffer = ""
            return out
        return None

    def _extract_chunk(self) -> tuple[str | None, str]:
        buf = self._buffer

        # Rule 1: sentence boundary (. ! ?) before space + capital
        for m in _SENTENCE_END_RE.finditer(buf):
            dot_pos = m.start(1)
            punc = m.group(1)
            if punc == "." and (_ends_with_abbreviation(buf, dot_pos) or _is_inside_decimal(buf, dot_pos)):
                continue
            split_at = m.start(2)
            return buf[:split_at].rstrip(), buf[split_at:]

        # Rule 2: strong clause boundary (; or :) followed by space
        strong = re.search(r'[;:]\s+', buf)
        if strong and len(buf) >= self._min:
            split_at = strong.end()
            return buf[:strong.start() + 1].rstrip(), buf[split_at:]

        # Rule 3: comma clause — ", " with 30+ chars after the comma, buffer >= min
        comma = re.search(r',\s+', buf)
        if comma and len(buf) >= self._min:
            tail_len = len(buf) - comma.end()
            if tail_len >= 30:
                split_at = comma.end()
                return buf[:comma.start() + 1].rstrip(), buf[split_at:]

        # Rule 4: hard cap — split at last space within max_chars
        if len(buf) >= self._max:
            segment = buf[:self._max]
            last_space = segment.rfind(" ")
            if last_space > 0:
                return buf[:last_space].rstrip(), buf[last_space + 1:]
            # No space at all — emit everything up to max_chars as one chunk
            return buf[:self._max], buf[self._max:]

        # Rule 5: nothing to emit yet
        return None, buf
