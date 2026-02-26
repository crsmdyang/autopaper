from __future__ import annotations

import re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from auto_paper.models import JournalSpec
from auto_paper.utils import normalize_whitespace, clamp_str


def fetch_guideline_text(url: str, timeout: int = 45) -> str:
    """
    Fetch and extract readable text from an Author Guideline URL.
    NOTE: Some publishers block scraping; in production add:
      - robots/ToS checks
      - playwright for dynamic pages
      - fallback: user uploads guideline PDF
    """
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "AutoPaperWriter/0.1"})
    r.raise_for_status()
    html = r.text
    soup = BeautifulSoup(html, "lxml")

    # Remove script/style/nav
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
        tag.decompose()

    # Prefer main/article
    main = soup.find("main") or soup.find("article") or soup.body
    text = main.get_text("\n", strip=True) if main else soup.get_text("\n", strip=True)

    # Clean up
    text = re.sub(r"\n{2,}", "\n", text)
    return normalize_whitespace(text)


def build_journal_spec_with_llm(
    llm_client,
    journal_name: str,
    guideline_url: str,
    guideline_text: str,
    article_type: str = "Original Article",
) -> JournalSpec:
    """
    Use LLM to extract structured constraints from guideline text.
    """
    system = (
        "You are an expert medical journal submission editor. "
        "Extract ONLY the submission-relevant constraints into JSON. "
        "Be conservative: if a value is not clearly stated, set it to null or omit."
    )

    user = f"""
Journal name: {journal_name}
Guideline URL: {guideline_url}
Target article type: {article_type}

Guideline text (truncated if long):
\"\"\"{clamp_str(guideline_text, 18000)}\"\"\"

Return JSON with these keys (all optional except journal_name):
{{
  "journal_name": "...",
  "guideline_url": "...",
  "article_type": "...",
  "abstract": {{
    "structured": true/false,
    "headings": ["Background","Methods","Results","Conclusion"],
    "word_limit": 250
  }},
  "main_text_sections_required": ["Introduction","Methods","Results","Discussion","Conclusion"],
  "main_text_word_limit": 4000,
  "references": {{
    "style": "Vancouver",
    "max_count": 30,
    "in_text_format": "bracket"|"paren",
    "allow_classic_exceptions": 2
  }},
  "tables_figures": {{
    "max_tables": 5,
    "max_figures": 6,
    "figure_dpi_min": 300
  }},
  "reporting_guideline_hint": ["STROBE"|"CONSORT"|"PRISMA"],
  "required_statements": ["Ethics approval statement", "Conflict of interest", "Funding", "Data availability"],
  "raw_guideline_text": "include the extracted guideline_text as-is (for audit)"
}}

Rules:
- If the guideline does not mention a limit (e.g., word limit), set it to null.
- If in-text citation format is unclear, default to "bracket".
- Always keep references style as "Vancouver" unless guideline explicitly states otherwise.
- raw_guideline_text: set to the provided guideline_text (not truncated) if possible.
"""

    data = llm_client.chat_json(system=system, user=user, temperature=0.0, max_tokens=2500)

    # Ensure raw text stored (for similarity checks)
    if "raw_guideline_text" not in data or not data["raw_guideline_text"]:
        data["raw_guideline_text"] = guideline_text

    # Validate via Pydantic
    return JournalSpec.model_validate(data)
