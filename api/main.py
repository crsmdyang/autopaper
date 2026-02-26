from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Dict, Optional, List, Any

from auto_paper.models import JournalSpec, StudyFactSheet, CitationPlan
from auto_paper.services.llm import OpenAIChatCompletionsClient
from auto_paper.services.journal_guideline import fetch_guideline_text, build_journal_spec_with_llm
from auto_paper.services.ingest import build_fact_sheet_with_llm
from auto_paper.services.section_writer import generate_section
from auto_paper.services.citations_pubmed import suggest_citations
from auto_paper.services.vancouver import assemble_main_text_and_references
from auto_paper.services.qa import run_qa
from auto_paper.services.similarity import similarity_report


app = FastAPI(title="Auto Paper Writer (Clinical) MVP")

llm = None


@app.on_event("startup")
def _startup():
    global llm
    llm = OpenAIChatCompletionsClient()


@app.get("/health")
def health():
    return {"ok": True}


class JournalParseRequest(BaseModel):
    journal_name: str
    guideline_url: str
    article_type: str = "Original Article"


@app.post("/journal/parse", response_model=JournalSpec)
def parse_journal(req: JournalParseRequest):
    text = fetch_guideline_text(req.guideline_url)
    spec = build_journal_spec_with_llm(llm, req.journal_name, req.guideline_url, text, article_type=req.article_type)
    return spec


class FactBuildRequest(BaseModel):
    plan_text: str
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    figures: List[Dict[str, Any]] = Field(default_factory=list)
    notes_for_writer: Optional[str] = None
    enable_vision_for_figures: bool = True


@app.post("/facts/build", response_model=StudyFactSheet)
def build_facts(req: FactBuildRequest):
    # Tables/Figures are already in model_dump format
    from auto_paper.models import TableData, FigureData
    tables = [TableData.model_validate(t) for t in req.tables]
    figures = [FigureData.model_validate(f) for f in req.figures]
    return build_fact_sheet_with_llm(
        llm,
        req.plan_text,
        tables,
        figures,
        notes_for_writer=req.notes_for_writer,
        enable_vision_for_figures=req.enable_vision_for_figures,
    )


class CitationSuggestRequest(BaseModel):
    topic: str
    intervention: Optional[str] = None
    comparator: Optional[str] = None
    outcomes: Optional[str] = None
    years_recent: int = 5
    retmax: int = 40
    include_abstracts: bool = False


@app.post("/citations/suggest")
def citations(req: CitationSuggestRequest):
    cits = suggest_citations(
        disease_or_topic=req.topic,
        intervention=req.intervention,
        comparator=req.comparator,
        outcomes=req.outcomes,
        years_recent=req.years_recent,
        retmax=req.retmax,
        include_abstracts=req.include_abstracts,
    )
    return {"citations": [c.model_dump() for c in cits]}


class SectionGenerateRequest(BaseModel):
    section: str
    journal: JournalSpec
    facts: StudyFactSheet
    citation_plan: CitationPlan
    user_overrides: Optional[str] = None
    two_pass: bool = True


@app.post("/section/generate")
def gen_section(req: SectionGenerateRequest):
    txt = generate_section(
        llm,
        req.section,
        req.journal,
        req.facts,
        req.citation_plan,
        user_overrides=req.user_overrides,
        two_pass=req.two_pass,
    )
    return {"section": req.section, "content": txt}


class AssembleRequest(BaseModel):
    journal: JournalSpec
    drafts: Dict[str, str]
    citation_plan: CitationPlan
    include_abstract_citations: bool = False


@app.post("/assemble")
def assemble(req: AssembleRequest):
    assembled, refs = assemble_main_text_and_references(
        req.journal, req.drafts, req.citation_plan, include_abstract_citations=req.include_abstract_citations
    )
    return {"assembled_main_text": assembled, "references": refs}


class QARequest(BaseModel):
    journal: JournalSpec
    facts: StudyFactSheet
    drafts: Dict[str, str]
    assembled_references: Optional[List[str]] = None
    citations_numbered: bool = False


@app.post("/qa")
def qa(req: QARequest):
    report = run_qa(
        req.journal,
        req.facts,
        req.drafts,
        assembled_references=req.assembled_references,
        citations_numbered=req.citations_numbered,
    )
    return report


class SimilarityRequest(BaseModel):
    generated: Dict[str, str]
    sources: Dict[str, str]
    threshold: float = 0.12


@app.post("/similarity")
def similarity(req: SimilarityRequest):
    results = similarity_report(req.generated, req.sources, threshold=req.threshold)
    return {"results": [r.__dict__ for r in results]}
