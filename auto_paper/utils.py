from __future__ import annotations

import re
from typing import Iterable


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def word_count(text: str) -> int:
    # simple English-ish word count
    tokens = re.findall(r"\b[\w'-]+\b", text)
    return len(tokens)


def split_sentences(text: str) -> list[str]:
    # naive sentence splitter (good enough for QA warnings)
    # avoids heavy NLP deps for MVP
    text = text.strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, max_chars: int = 4000) -> list[str]:
    # chunk by paragraphs
    paras = text.split("\n\n")
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 2 <= max_chars:
            buf = (buf + "\n\n" + p).strip()
        else:
            if buf:
                out.append(buf)
            buf = p.strip()
    if buf:
        out.append(buf)
    return out


def clamp_str(s: str, max_len: int) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len-1] + "…"
