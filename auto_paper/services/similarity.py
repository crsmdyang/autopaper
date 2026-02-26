from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Set, Optional

from auto_paper.utils import normalize_whitespace


def _tokens(text: str) -> List[str]:
    text = normalize_whitespace(text.lower())
    return re.findall(r"[a-z0-9]+", text)


def _hash_ngram(tokens: List[str], start: int, k: int) -> int:
    # simple rolling hash substitute (not cryptographic)
    h = 1469598103934665603  # FNV offset basis (64-bit)
    for i in range(start, start + k):
        for ch in tokens[i]:
            h ^= ord(ch)
            h *= 1099511628211
            h &= 0xFFFFFFFFFFFFFFFF
        h ^= 0xFF
        h *= 1099511628211
        h &= 0xFFFFFFFFFFFFFFFF
    return h


def winnow_fingerprints(text: str, k: int = 5, window: int = 4) -> Set[int]:
    toks = _tokens(text)
    if len(toks) < k:
        return set()
    hashes = [_hash_ngram(toks, i, k) for i in range(len(toks) - k + 1)]
    if len(hashes) <= window:
        return set(hashes)

    fps: Set[int] = set()
    min_hash = None
    min_pos = -1
    for i in range(len(hashes) - window + 1):
        # find min in window [i, i+window)
        window_hashes = hashes[i:i+window]
        m = min(window_hashes)
        pos = i + window_hashes.index(m)
        if pos != min_pos or m != min_hash:
            fps.add(m)
            min_hash = m
            min_pos = pos
    return fps


def jaccard(a: Set[int], b: Set[int]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


@dataclass
class SimilarityResult:
    name_a: str
    name_b: str
    score: float  # 0..1


def similarity_score(text_a: str, text_b: str, k: int = 5, window: int = 4) -> float:
    fa = winnow_fingerprints(text_a, k=k, window=window)
    fb = winnow_fingerprints(text_b, k=k, window=window)
    return jaccard(fa, fb)


def similarity_report(
    generated: Dict[str, str],
    sources: Dict[str, str],
    threshold: float = 0.12,
) -> List[SimilarityResult]:
    """
    Compare each generated section to each source text and report pairs above threshold.
    Threshold is heuristic; tune for your needs.
    """
    results: List[SimilarityResult] = []
    for ga, ta in generated.items():
        if not ta or not ta.strip():
            continue
        for sb, tb in sources.items():
            if not tb or not tb.strip():
                continue
            score = similarity_score(ta, tb)
            if score >= threshold:
                results.append(SimilarityResult(name_a=ga, name_b=sb, score=score))
    results.sort(key=lambda x: x.score, reverse=True)
    return results
