from __future__ import annotations

import re
from typing import Dict, List, Tuple, Any, Optional, Set

from auto_paper.models import JournalSpec, StudyFactSheet
from auto_paper.utils import word_count, split_sentences


CLAIM_PATTERNS = [
    re.compile(r"\bhas been (shown|reported|demonstrated)\b", re.I),
    re.compile(r"\bprevious (studies|reports)\b", re.I),
    re.compile(r"\baccording to\b", re.I),
    re.compile(r"\bguideline(s)?\b", re.I),
    re.compile(r"\bmeta-?analysis\b", re.I),
    re.compile(r"\bsystematic review\b", re.I),
    re.compile(r"\brandomized\b", re.I),
]

CITE_PLACEHOLDER = re.compile(r"\{cite:(PMID|DOI):[^}]+\}")
CITE_NUMBERED = re.compile(r"\[(\d+)\]|\((\d+)\)")


def _extract_numbers(text: str) -> List[str]:
    # captures integers/decimals, percentages, p-values, HR/CI fragments
    return re.findall(r"\b\d+(?:\.\d+)?\b", text)


def _numbers_from_facts(facts: StudyFactSheet) -> Set[str]:
    nums: Set[str] = set()
    # groups N
    for g in facts.population.groups:
        if g.n is not None:
            nums.add(str(g.n))
    # tables
    for t in facts.tables:
        for row in t.rows:
            for cell in row:
                for n in _extract_numbers(str(cell)):
                    nums.add(n)
        for f in t.key_findings:
            if f.p_value:
                for n in _extract_numbers(f.p_value):
                    nums.add(n)
            if f.ci_95:
                for n in _extract_numbers(f.ci_95):
                    nums.add(n)
            for v in f.values.values():
                for n in _extract_numbers(str(v)):
                    nums.add(n)
    # plan text (very loose)
    if facts.plan_text:
        for n in _extract_numbers(facts.plan_text):
            nums.add(n)
    # common allowed constants
    nums.update({"0.05", "95"})
    return nums


def check_abstract(journal: JournalSpec, abstract_text: str) -> List[str]:
    warnings = []
    wc = word_count(abstract_text)
    limit = journal.abstract.word_limit or 250
    if wc > limit:
        warnings.append(f"Abstract word count {wc} exceeds limit {limit}.")
    if journal.abstract.structured:
        # require headings
        for h in journal.abstract.headings:
            if re.search(rf"^{re.escape(h)}\s*:", abstract_text, re.M) is None:
                warnings.append(f"Abstract missing structured heading: {h}:")
                break
    return warnings


def check_reference_count(journal: JournalSpec, references: List[str]) -> List[str]:
    warnings = []
    if len(references) > journal.references.max_count:
        warnings.append(
            f"Reference count {len(references)} exceeds max {journal.references.max_count}. "
            f"Reduce citations or revise CitationPlan."
        )
    return warnings


def check_claims_need_citations(text: str, allow_placeholders: bool = True) -> List[str]:
    warnings = []
    for sent in split_sentences(text):
        if any(p.search(sent) for p in CLAIM_PATTERNS):
            has_cite = bool(CITE_PLACEHOLDER.search(sent)) if allow_placeholders else bool(CITE_NUMBERED.search(sent))
            if not has_cite:
                warnings.append(f"Sentence likely needs a citation: {sent[:180]}{'…' if len(sent)>180 else ''}")
    return warnings


def check_numbers_not_in_facts(facts: StudyFactSheet, text: str, max_reports: int = 20) -> List[str]:
    warnings = []
    fact_nums = _numbers_from_facts(facts)
    txt_nums = _extract_numbers(text)
    unknown = []
    for n in txt_nums:
        if n not in fact_nums:
            # allow common years if present in facts? This is tricky; treat as warning only.
            unknown.append(n)
    if unknown:
        sample = ", ".join(unknown[:max_reports])
        warnings.append(f"Text contains numeric tokens not found in FactSheet (possible hallucination): {sample}")
    return warnings


def run_qa(
    journal: JournalSpec,
    facts: StudyFactSheet,
    drafts: Dict[str, str],
    assembled_references: Optional[List[str]] = None,
    citations_numbered: bool = False,
) -> Dict[str, Any]:
    """
    Returns dict with warnings by section + global warnings.
    """
    report: Dict[str, Any] = {"global": [], "by_section": {}}

    # Required sections present?
    for sec in journal.main_text_sections_required:
        if sec not in drafts or not drafts[sec].strip():
            report["global"].append(f"Missing or empty section: {sec}")

    # Abstract checks
    if "Abstract" in drafts and drafts["Abstract"].strip():
        report["by_section"]["Abstract"] = []
        report["by_section"]["Abstract"].extend(check_abstract(journal, drafts["Abstract"]))
        report["by_section"]["Abstract"].extend(check_numbers_not_in_facts(facts, drafts["Abstract"]))

    # Claims needing citations: Intro/Discussion most important
    for sec in ["Introduction", "Discussion"]:
        if sec in drafts and drafts[sec].strip():
            report["by_section"].setdefault(sec, [])
            report["by_section"][sec].extend(
                check_claims_need_citations(drafts[sec], allow_placeholders=not citations_numbered)
            )

    # Numbers hallucination check (warning)
    for sec, txt in drafts.items():
        if not txt or not txt.strip():
            continue
        report["by_section"].setdefault(sec, [])
        report["by_section"][sec].extend(check_numbers_not_in_facts(facts, txt))

    # Reference count
    if assembled_references is not None:
        report["global"].extend(check_reference_count(journal, assembled_references))

    return report
