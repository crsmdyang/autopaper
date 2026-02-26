from __future__ import annotations

import re
from typing import Dict, List, Tuple, Optional

from auto_paper.models import CitationPlan, Citation, JournalSpec


CITE_PATTERN = re.compile(r"\{cite:(PMID|DOI):([^}]+)\}")


def _format_authors(authors: List[str]) -> str:
    if not authors:
        return ""
    # Vancouver: list up to 6, then et al.
    if len(authors) <= 6:
        return ", ".join(authors) + "."
    return ", ".join(authors[:6]) + ", et al."


def format_vancouver_reference(c: Citation) -> str:
    """
    Simplified Vancouver/NLM-ish formatting.
    Real-world formatting may vary slightly by journal.
    """
    a = _format_authors(c.authors)
    title = (c.title or "").rstrip(".")
    journal = c.journal_iso_abbrev or c.journal or ""
    year = str(c.year) if c.year else ""
    vol = c.volume or ""
    issue = c.issue or ""
    pages = c.pages or ""
    doi = c.doi or ""
    parts = []

    if a:
        parts.append(a)
    if title:
        parts.append(f"{title}.")
    if journal:
        parts.append(f"{journal}.")

    if year:
        vol_issue = vol
        if issue:
            vol_issue = f"{vol}({issue})" if vol else f"({issue})"
        if pages:
            parts.append(f"{year};{vol_issue}:{pages}.")
        else:
            parts.append(f"{year};{vol_issue}.")
    elif journal:
        # keep minimal; do nothing
        pass

    if doi:
        parts.append(f"doi:{doi}.")
    elif c.url:
        parts.append(c.url)

    ref = " ".join([p for p in parts if p is not None and str(p).strip() != ""])
    ref = re.sub(r"\s{2,}", " ", ref).strip()
    return ref


def _key(kind: str, ident: str) -> str:
    return f"{kind}:{ident.strip()}"


def re_number_citations(
    text: str,
    key_to_num: Dict[str, int],
    next_num: int,
    in_text_format: str = "bracket",
) -> Tuple[str, Dict[str, int], int]:
    """
    Replace cite placeholders with sequential numbers, preserving first-appearance order.
    """
    def repl(m: re.Match) -> str:
        nonlocal next_num
        kind, ident = m.group(1), m.group(2)
        k = _key(kind, ident)
        if k not in key_to_num:
            key_to_num[k] = next_num
            next_num += 1
        num = key_to_num[k]
        return f"[{num}]" if in_text_format == "bracket" else f"({num})"

    new_text = CITE_PATTERN.sub(repl, text)
    return new_text, key_to_num, next_num


def number_drafts_and_build_references(
    journal: JournalSpec,
    drafts: Dict[str, str],
    citation_plan: CitationPlan,
    include_abstract_citations: bool = False,
) -> Tuple[Dict[str, str], List[str]]:
    """
    Returns:
      - numbered_drafts: same keys as drafts (subset), but cite placeholders converted to [n]/(n)
      - references: Vancouver list ordered by first appearance in (Abstract?) + IMRaD
    """
    order = ["Introduction", "Methods", "Results", "Discussion", "Conclusion"]
    if include_abstract_citations and "Abstract" in drafts:
        order = ["Abstract"] + order

    key_to_num: Dict[str, int] = {}
    next_num = 1
    numbered: Dict[str, str] = {}

    for sec in order:
        if sec not in drafts or not drafts[sec] or not drafts[sec].strip():
            continue
        sec_text = drafts[sec].strip()
        sec_text, key_to_num, next_num = re_number_citations(
            sec_text, key_to_num, next_num, in_text_format=journal.references.in_text_format
        )
        numbered[sec] = sec_text

    # Map keys to citations
    key_to_citation: Dict[str, Citation] = {}
    for cu in citation_plan.selected:
        c = cu.citation
        if c.pmid:
            key_to_citation[_key("PMID", c.pmid)] = c
        if c.doi:
            key_to_citation[_key("DOI", c.doi)] = c

    num_to_key = {num: key for key, num in key_to_num.items()}

    refs: List[str] = []
    for num in sorted(num_to_key.keys()):
        key = num_to_key[num]
        c = key_to_citation.get(key)
        if c:
            refs.append(f"{num}. {format_vancouver_reference(c)}")
        else:
            refs.append(f"{num}. {key} (Missing metadata; please fix in CitationPlan).")

    return numbered, refs


def assemble_main_text_and_references(
    journal: JournalSpec,
    drafts: Dict[str, str],
    citation_plan: CitationPlan,
    include_abstract_citations: bool = False,
) -> Tuple[str, List[str]]:
    numbered, refs = number_drafts_and_build_references(
        journal=journal,
        drafts=drafts,
        citation_plan=citation_plan,
        include_abstract_citations=include_abstract_citations,
    )

    parts: List[str] = []
    if include_abstract_citations and "Abstract" in numbered:
        parts.append(f"Abstract\n\n{numbered['Abstract']}")

    for sec in ["Introduction", "Methods", "Results", "Discussion", "Conclusion"]:
        if sec in numbered:
            parts.append(f"{sec}\n\n{numbered[sec]}")

    assembled = "\n\n".join(parts).strip()
    return assembled, refs
