from __future__ import annotations

from typing import List, Optional, Dict, Any
import time
import requests
from datetime import datetime

from auto_paper.config import settings
from auto_paper.models import Citation


PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedError(RuntimeError):
    pass


def _headers() -> Dict[str, str]:
    # NCBI recommends including an email in tool identification
    return {"User-Agent": f"AutoPaperWriter/0.1 ({settings.user_agent_email})"}


def search_pubmed(term: str, retmax: int = 30) -> List[str]:
    params = {
        "db": "pubmed",
        "term": term,
        "retmode": "json",
        "retmax": str(retmax),
        "sort": "relevance",
    }
    r = requests.get(PUBMED_ESEARCH, params=params, headers=_headers(), timeout=45)
    if r.status_code >= 400:
        raise PubMedError(f"PubMed esearch error {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data.get("esearchresult", {}).get("idlist", []) or []


def fetch_summaries(pmids: List[str]) -> List[Citation]:
    if not pmids:
        return []
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
    }
    r = requests.get(PUBMED_ESUMMARY, params=params, headers=_headers(), timeout=45)
    if r.status_code >= 400:
        raise PubMedError(f"PubMed esummary error {r.status_code}: {r.text[:300]}")
    data = r.json()
    result = data.get("result", {})
    out: List[Citation] = []
    for pmid in pmids:
        item: Dict[str, Any] = result.get(pmid, {})
        if not item:
            continue
        authors = [a.get("name") for a in item.get("authors", []) if a.get("name")]
        pubtypes = item.get("pubtype", []) or []
        year = None
        pubdate = item.get("pubdate", "")
        try:
            year = int(pubdate[:4])
        except Exception:
            year = None

        # PubMed "elocationid" sometimes includes DOI; not always.
        eloc = item.get("elocationid") or ""
        doi = eloc if eloc.startswith("10.") else None

        out.append(
            Citation(
                pmid=pmid,
                doi=doi,
                title=(item.get("title", "") or "").strip().rstrip("."),
                authors=authors,
                journal=item.get("fulljournalname") or item.get("source"),
                journal_iso_abbrev=item.get("source"),
                year=year,
                volume=item.get("volume"),
                issue=item.get("issue"),
                pages=item.get("pages"),
                publication_types=[str(p) for p in pubtypes],
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            )
        )
    return out


def fetch_abstracts(pmids: List[str]) -> Dict[str, str]:
    """Fetch PubMed abstracts via EFetch (XML) and return {pmid: abstract_text}."""
    if not pmids:
        return {}
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    r = requests.get(PUBMED_EFETCH, params=params, headers=_headers(), timeout=60)
    if r.status_code >= 400:
        raise PubMedError(f"PubMed efetch error {r.status_code}: {r.text[:300]}")

    import xml.etree.ElementTree as ET

    root = ET.fromstring(r.text)
    out: Dict[str, str] = {}
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        if pmid_el is None or not (pmid_el.text or "").strip():
            continue
        pmid = (pmid_el.text or "").strip()
        abs_els = art.findall(".//Article/Abstract/AbstractText")
        if not abs_els:
            continue
        parts = []
        for a in abs_els:
            label = a.attrib.get("Label") or a.attrib.get("NlmCategory")
            txt = (a.text or "").strip()
            if not txt:
                continue
            if label:
                parts.append(f"{label}: {txt}")
            else:
                parts.append(txt)
        if parts:
            out[pmid] = "\n".join(parts)
    return out


def suggest_citations(
    disease_or_topic: str,
    intervention: Optional[str] = None,
    comparator: Optional[str] = None,
    outcomes: Optional[str] = None,
    years_recent: int = 5,
    retmax: int = 40,
    include_abstracts: bool = False,
) -> List[Citation]:
    """
    Simple query builder for MVP:
    - Bias toward RCT/Systematic Review/Guideline/Meta-analysis
    - Bias toward recent years, but does not hard-block older classics
    """
    query_parts = [disease_or_topic]
    if intervention:
        query_parts.append(intervention)
    if comparator:
        query_parts.append(comparator)
    if outcomes:
        query_parts.append(outcomes)

    pubtype_bias = '(randomized controlled trial[pt] OR systematic review[pt] OR guideline[pt] OR meta-analysis[pt])'
    term_core = " AND ".join([f"({p})" for p in query_parts if p and p.strip()])
    if term_core:
        term = f"({term_core}) AND {pubtype_bias}"
    else:
        term = pubtype_bias

    current_year = datetime.utcnow().year
    start_year = current_year - years_recent
    # PubMed date range on [dp] is an approximation; adjust later if needed.
    term = f"{term} AND (\"{start_year}\"[dp] : \"3000\"[dp])"

    pmids = search_pubmed(term, retmax=retmax)
    # Respect NCBI rate limits (be nice)
    time.sleep(0.34)
    cits = fetch_summaries(pmids)
    if include_abstracts and cits:
        time.sleep(0.34)
        abs_map = fetch_abstracts([c.pmid for c in cits if c.pmid])
        for c in cits:
            if c.pmid and c.pmid in abs_map:
                c.abstract = abs_map[c.pmid]
    return cits
