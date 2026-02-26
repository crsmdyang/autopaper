from __future__ import annotations

from typing import Tuple, List, Optional

from auto_paper.models import JournalSpec, StudyFactSheet, CitationPlan, SectionName
from auto_paper.utils import clamp_str


def _citations_compact(plan: CitationPlan, limit: int = 35) -> str:
    # Provide compact list for the model; it must NOT invent citations outside this list.
    items = []
    for cu in plan.selected[:limit]:
        c = cu.citation
        key = f"PMID:{c.pmid}" if c.pmid else (f"DOI:{c.doi}" if c.doi else "UNKNOWN")
        year = c.year or ""
        j = c.journal_iso_abbrev or c.journal or ""
        pt = ", ".join(c.publication_types[:3])
        uses = ",".join(cu.use_for)
        abs_snip = clamp_str((c.abstract or "").replace("\n", " "), 240)
        abs_part = f" | abs:{abs_snip}" if abs_snip else ""
        items.append(f"- {key} | {year} | {j} | {clamp_str(c.title, 120)} | types:{pt} | use_for:{uses}{abs_part}")
    if not items:
        return "(No citations selected yet.)"
    return "\n".join(items)


def _facts_pack(
    facts: StudyFactSheet,
    section: SectionName,
    max_tables: int = 8,
    max_figures: int = 8,
    table_preview_rows: int = 30,
    table_preview_cols: int = 14,
) -> str:
    """Token-aware "evidence pack" passed to the model.

    Key design choice:
    - For Results: include compact table previews + extracted key_findings + figure key points.
    - For other sections: include mainly study metadata + table/figure digests (not full tables).
    """

    groups = ", ".join([f"{g.name}(n={g.n})" for g in facts.population.groups]) or "N/A"
    stats = ", ".join(facts.statistics.methods) or "N/A"

    # Table digest (always)
    table_lines = []
    for t in facts.tables[:max_tables]:
        cat = t.category or "Other"
        title = t.title or "Untitled"
        table_lines.append(f"- {t.id} ({cat}): {title} | rows={len(t.rows)} cols={len(t.header)}")
        if t.key_findings:
            for kf in t.key_findings[:8]:
                pv = f"; p={kf.p_value}" if kf.p_value else ""
                table_lines.append(f"  • {clamp_str(kf.statement, 180)}{pv}")

    # Full table previews only when Results (and optionally Abstract)
    table_previews = []
    if section in ("Results", "Abstract"):
        from auto_paper.services.ingest import table_to_markdown  # local import to avoid circular
        for t in facts.tables[:max_tables]:
            md = table_to_markdown(t, max_rows=table_preview_rows, max_cols=table_preview_cols)
            table_previews.append(f"\n\n### {t.id}: {t.title or 'Untitled'}\n{md}")

    # Figures
    fig_lines = []
    for f in facts.figures[:max_figures]:
        cap = clamp_str(f.caption_raw or "", 140)
        fig_lines.append(f"- {f.id} ({f.figure_type}): {f.filename} | caption={cap}")
        if f.key_points:
            for kp in f.key_points[:8]:
                fig_lines.append(f"  • {clamp_str(kp, 180)}")

    return f"""
STUDY TITLE: {facts.title or "N/A"}
KEYWORDS: {", ".join(facts.keywords) if facts.keywords else "N/A"}
DESIGN: {facts.study_design or "N/A"}
PERIOD: {facts.period.start or "?"} to {facts.period.end or "?"}
IRB: approved={facts.irb.approved}, number={facts.irb.number or "N/A"}

PROTOCOL KEY POINTS:
{chr(10).join(["- " + x for x in facts.protocol_key_points[:18]]) if facts.protocol_key_points else "- (not specified)"}

POPULATION / GROUPS:
- {groups}

INCLUSION:
{chr(10).join(["- " + x for x in facts.population.inclusion[:12]]) if facts.population.inclusion else "- not specified"}

EXCLUSION:
{chr(10).join(["- " + x for x in facts.population.exclusion[:12]]) if facts.population.exclusion else "- not specified"}

ENDPOINTS:
- Primary: {facts.endpoints.primary or "not specified"}
- Secondary: {", ".join(facts.endpoints.secondary) if facts.endpoints.secondary else "not specified"}

STATISTICS:
- alpha={facts.statistics.alpha}
- software: {facts.statistics.software or "not specified"}
- methods: {stats}
- notes: {facts.statistics.notes or ""}

TABLE DIGEST:
{chr(10).join(table_lines) if table_lines else "- (none)"}

FIGURE DIGEST:
{chr(10).join(fig_lines) if fig_lines else "- (none)"}

TABLE PREVIEWS (ONLY USE IF PROVIDED BELOW):
{"".join(table_previews) if table_previews else "(not provided for this section)"}

AUTHOR NOTES:
{facts.notes_for_writer or ""}
""".strip()


def _outline_system() -> str:
    return (
        "You are a senior medical writer. Create an evidence-grounded outline before drafting prose. "
        "STRICT RULES: (1) Do NOT invent any numeric values. (2) Use only information present in the evidence pack. "
        "(3) If something is unknown, mark it as 'not specified'. "
        "Output must be English."
    )


def _prose_system() -> str:
    return (
        "You are a senior medical writer for SCI clinical manuscripts. "
        "Write clear, concise academic English. "
        "STRICT RULES:\n"
        "1) Do NOT invent any numeric values (N, p-values, HR, CI, means, SD, percentages) not explicitly present in the provided evidence pack / outline.\n"
        "2) Do NOT invent references. You may cite ONLY from the provided citation list, using placeholders.\n"
        "3) Use citation placeholders ONLY (no numeric [1] in-text citations here).\n"
        "4) Do NOT include a References section here.\n"
        "5) Avoid verbatim copying from the protocol/guidelines. Paraphrase and be original.\n"
        "6) For Results: report FACTS only; save interpretations for Discussion.\n"
    )


def build_section_messages(
    section: SectionName,
    journal: JournalSpec,
    facts: StudyFactSheet,
    citation_plan: CitationPlan,
    user_overrides: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Returns (system, user) messages for the LLM.
    Output must be English. Citations must be placeholders:
      - {cite:PMID:12345678} or {cite:DOI:10.xxxx/yyy}
    """
    system = _prose_system()

    spec = journal.model_dump()
    facts_txt = _facts_pack(facts, section)
    cites_txt = _citations_compact(citation_plan)

    # Section-specific instructions (align to user's writing rules)
    if section == "Abstract":
        abstract_spec = journal.abstract
        word_limit = abstract_spec.word_limit or 250
        headings = abstract_spec.headings if abstract_spec.structured else []
        user = f"""
Write a structured Abstract in English for a clinical original article.

Journal constraints:
- Structured: {abstract_spec.structured}
- Headings (use EXACT headings): {headings}
- Word limit: {word_limit} words (hard limit)
- Use concrete numbers from provided tables when available (include p-values and/or 95% CI when present).
- Mention study design, group sizes (N), and key statistical approach if available.

Facts (compact):
{facts_txt}

Allowed citations (use placeholders only, sparingly in abstract; optional):
{cites_txt}

Output format:
If structured, output exactly 4 paragraphs with these headings and a colon.
Example:
Background: ...
Methods: ...
Results: ...
Conclusion: ...

Additional user overrides:
{user_overrides or ""}
"""
        return system, user

    if section == "Introduction":
        user = f"""
Write the Introduction (300–500 words) in English, using a 3-paragraph funnel structure:
Paragraph 1 (What is known): clinical background and established knowledge.
Paragraph 2 (The Gap): limitations of existing studies and unmet need.
Paragraph 3 (The Aim): explicit objective/hypothesis of THIS study.

Rules:
- Do not repeat Results.
- Keep it focused and modern.
- Cite 4–8 key references (placeholders) from the allowed list, prioritizing recent (≤5 years) RCT/SR/Guideline, with up to 1–2 classic exceptions if necessary.

Facts (compact):
{facts_txt}

Allowed citations (placeholders only):
{cites_txt}

Additional user overrides:
{user_overrides or ""}
"""
        return system, user

    if section == "Methods":
        user = f"""
Write the Methods section (500–1000 words) in English, reproducible and audit-ready.

Must include (if available):
- Study design and setting (single-center vs multicenter)
- Study period
- IRB approval number and waiver/consent statement if in facts
- Inclusion/exclusion criteria
- Surgical technique description (brief unless special technique)
- Endpoints definitions (primary/secondary)
- Statistical analysis: software + version if available, alpha (p<0.05), tests/models (Chi-square, t-test, Kaplan–Meier/log-rank, Cox, PSM, etc.)

Rules:
- If something is unknown, write it as "not specified" rather than inventing.
- Cite guidelines/standard methods where appropriate (placeholders).

Facts (compact):
{facts_txt}

Allowed citations (placeholders only):
{cites_txt}

Additional user overrides:
{user_overrides or ""}
"""
        return system, user

    if section == "Results":
        user = f"""
Write the Results section (500–800 words) in English.
Structure 4–6 paragraphs, facts only:

P1: Baseline characteristics (Table 1 summary).
P2: Perioperative outcomes (operative time, blood loss, complications, LOS, etc).
P3: Pathologic outcomes (lymph nodes, CRM, margins, staging).
P4: Oncologic outcomes if present (Kaplan–Meier survival, recurrence; report HR/p/CI only if provided).
(P5–6 optional): Subgroup/sensitivity analyses (e.g., PSM) if in facts.

Rules:
- Do NOT interpret. No "this suggests" or "this may be due to".
- Do not repeat every number from tables; highlight significant findings (p<0.05) and clinically important trends.
- You may reference tables/figures as (Table 1), (Figure 1), but do not fabricate table/figure numbers beyond provided IDs.

Facts (compact):
{facts_txt}

Allowed citations (generally minimal in Results; placeholders only if needed for standard definitions):
{cites_txt}

Additional user overrides:
{user_overrides or ""}
"""
        return system, user

    if section == "Discussion":
        user = f"""
Write the Discussion section (1200–1500 words) in English with an inverted funnel:

P1 Summary: main finding(s) in 1 paragraph (do NOT repeat the introduction).
P2–P5 Interpretation & comparison: discuss each key result and compare with prior literature.
P6 Mechanism/implication: clinical meaning and why it matters.
P7 Limitations: honest limitations + strengths that mitigate them.
P8 Closing paragraph: balanced take-home message + suggestion for future RCT/large studies.

Rules:
- Must cite relevant RCT/SR/guidelines from allowed list (placeholders).
- Be conservative: no overclaiming beyond data.
- Avoid plagiarism; paraphrase.

Facts (compact):
{facts_txt}

Allowed citations (placeholders only):
{cites_txt}

Additional user overrides:
{user_overrides or ""}
"""
        return system, user

    if section == "Conclusion":
        user = f"""
Write a 100–150 word Conclusion in English (single paragraph).

Rules:
- Directly answer the aim.
- No overclaiming.
- Typically end with a recommendation for future large-scale studies/RCT if appropriate.

Facts (compact):
{facts_txt}

Allowed citations (usually none in conclusion; if used, placeholders only):
{cites_txt}

Additional user overrides:
{user_overrides or ""}
"""
        return system, user

    if section == "CoverLetter":
        user = f"""
Write a cover letter (300–400 words, within 1 page) addressed to the Editor-in-Chief.

Structure 3–4 paragraphs:
P1 Submission intent + why this journal is a good fit (use journal_name).
P2 The hook: novelty + clinical significance (main finding).
P3 Declarations: all authors approved, not under consideration elsewhere, COI statement (and ethics approval if applicable).
(Optional) P4 Suggested reviewers / data availability if user wants (omit unless specified).

Rules:
- Do not exaggerate.
- Do NOT include references list.

Journal:
- {journal.journal_name}
- Article type: {journal.article_type}

Facts (compact):
{facts_txt}

Additional user overrides:
{user_overrides or ""}
"""
        return system, user

    raise ValueError(f"Unsupported section: {section}")


def build_section_outline_messages(
    section: SectionName,
    journal: JournalSpec,
    facts: StudyFactSheet,
    user_overrides: Optional[str] = None,
) -> Tuple[str, str]:
    """Return (system, user) for outline-only generation (no citations)."""
    system = _outline_system()
    facts_txt = _facts_pack(facts, section)

    if section == "Abstract":
        abstract_spec = journal.abstract
        headings = abstract_spec.headings if abstract_spec.structured else []
        return system, f"""
Create an evidence-grounded outline for the Abstract.

Journal constraints:
- Structured: {abstract_spec.structured}
- Headings (use EXACT headings): {headings}
- Word limit (final abstract): {abstract_spec.word_limit or 250}

Output requirements:
- Output an outline only (bullet points), NOT full prose.
- Include: study design, group sizes if known, primary endpoint, and 3–5 key numerical results if they are explicitly present in the table previews.
- For every numeric claim, append the source in parentheses, e.g., (Table T1) or (Figure F1).

Evidence pack:
{facts_txt}

Additional user overrides:
{user_overrides or ""}
"""

    if section == "Introduction":
        return system, f"""
Create a 3-paragraph Introduction outline (bulleted), using a funnel structure:
P1 What is known; P2 The gap; P3 Aim/hypothesis.

Rules:
- No citations yet (we will add later).
- Do not include Results interpretation.
- Keep it clinically focused.

Evidence pack:
{facts_txt}

Additional user overrides:
{user_overrides or ""}
"""

    if section == "Methods":
        return system, f"""
Create a detailed Methods outline (bulleted) that could be expanded into a full Methods section.

Must include headings/subheadings:
- Study design and setting
- Study population (inclusion/exclusion)
- Interventions / procedures (if applicable)
- Outcome definitions (primary/secondary)
- Statistical analysis plan
- Ethics

Rules:
- Use 'not specified' for missing details.
- No citations yet.

Evidence pack:
{facts_txt}

Additional user overrides:
{user_overrides or ""}
"""

    if section == "Results":
        return system, f"""
Create a Results outline (bulleted) organized into 4–6 paragraphs:
P1 Baseline characteristics (Table 1)
P2 Perioperative outcomes
P3 Pathologic outcomes
P4 Oncologic outcomes / survival (Figures)
P5–6 optional: subgroup/sensitivity analyses

Rules:
- Facts only (no interpretation).
- Prefer to use extracted key_findings first; if a key number is missing there but present in table previews, you may quote it.
- For EVERY number, append (Table T#) or (Figure F#).

Evidence pack:
{facts_txt}

Additional user overrides:
{user_overrides or ""}
"""

    if section == "Discussion":
        return system, f"""
Create a Discussion outline (bulleted) with an inverted funnel:
P1 Summary of main findings
P2–P5 Interpretation and comparison to prior literature (no citations yet, just placeholders like [CITE])
P6 Clinical implications
P7 Limitations and strengths
P8 Conclusion and future directions

Rules:
- Be conservative; no overclaiming.
- No citations yet (we will add later).

Evidence pack:
{facts_txt}

Additional user overrides:
{user_overrides or ""}
"""

    if section == "Conclusion":
        return system, f"""
Create a 1-paragraph Conclusion outline (bulleted -> 5–7 bullets max).

Rules:
- Directly answer the aim.
- No overclaiming; no citations.

Evidence pack:
{facts_txt}

Additional user overrides:
{user_overrides or ""}
"""

    if section == "CoverLetter":
        return system, f"""
Create a cover letter outline (bulleted) addressed to the Editor-in-Chief.

Include:
- Submission intent and fit to journal
- Novelty and clinical significance
- Ethics/COI declarations

Evidence pack:
{facts_txt}

Journal:
- {journal.journal_name}
- Article type: {journal.article_type}

Additional user overrides:
{user_overrides or ""}
"""

    raise ValueError(f"Unsupported section: {section}")


def generate_section(
    llm_client,
    section: SectionName,
    journal: JournalSpec,
    facts: StudyFactSheet,
    citation_plan: CitationPlan,
    user_overrides: Optional[str] = None,
    temperature: float = 0.3,
    two_pass: bool = True,
) -> str:
    if not two_pass:
        system, user = build_section_messages(section, journal, facts, citation_plan, user_overrides=user_overrides)
        resp = llm_client.chat_text(system=system, user=user, temperature=temperature, max_tokens=2500)
        return resp.text.strip()

    # Pass 1) Evidence-grounded outline (NO citations)
    sys1, usr1 = build_section_outline_messages(section, journal, facts, user_overrides=user_overrides)
    outline = llm_client.chat_text(system=sys1, user=usr1, temperature=0.2, max_tokens=1400).text.strip()

    # Pass 2) Expand outline into prose WITH allowed citations
    sys2, usr2 = build_section_messages(section, journal, facts, citation_plan, user_overrides=user_overrides)
    usr2 = (
        usr2.strip()
        + "\n\n=== EVIDENCE-GROUNDED OUTLINE (MUST FOLLOW; DO NOT ADD NEW NUMBERS) ===\n"
        + outline
        + "\n\nNow expand this outline into final prose for this section. "
          "Do not introduce any new numeric values not already present in the outline or evidence pack."
    )
    resp2 = llm_client.chat_text(system=sys2, user=usr2, temperature=temperature, max_tokens=2600)
    return resp2.text.strip()
