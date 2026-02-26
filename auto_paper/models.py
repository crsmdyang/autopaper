from __future__ import annotations

from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


class AbstractSpec(BaseModel):
    structured: bool = True
    headings: List[str] = Field(default_factory=lambda: ["Background", "Methods", "Results", "Conclusion"])
    word_limit: Optional[int] = 250


class ReferencesSpec(BaseModel):
    style: Literal["Vancouver"] = "Vancouver"
    max_count: int = 30
    in_text_format: Literal["bracket", "paren"] = "bracket"  # [1] vs (1)
    allow_classic_exceptions: int = 2  # allow 1–2 classic/older references if needed


class TablesFiguresSpec(BaseModel):
    max_tables: Optional[int] = None
    max_figures: Optional[int] = None
    figure_dpi_min: Optional[int] = 300


class JournalSpec(BaseModel):
    journal_name: str
    guideline_url: Optional[str] = None
    article_type: str = "Original Article"
    abstract: AbstractSpec = Field(default_factory=AbstractSpec)
    main_text_sections_required: List[str] = Field(
        default_factory=lambda: ["Introduction", "Methods", "Results", "Discussion", "Conclusion"]
    )
    main_text_word_limit: Optional[int] = None
    references: ReferencesSpec = Field(default_factory=ReferencesSpec)
    tables_figures: TablesFiguresSpec = Field(default_factory=TablesFiguresSpec)
    reporting_guideline_hint: List[str] = Field(default_factory=list)  # e.g., ["STROBE"]
    required_statements: List[str] = Field(default_factory=list)  # e.g., COI, Ethics, Data availability
    raw_guideline_text: Optional[str] = None  # stored for internal similarity checks / audit


class IRBInfo(BaseModel):
    approved: bool = False
    number: Optional[str] = None


class StudyPeriod(BaseModel):
    start: Optional[str] = None  # YYYY-MM-DD
    end: Optional[str] = None


class GroupInfo(BaseModel):
    name: str
    n: Optional[int] = None
    definition: Optional[str] = None


class PopulationInfo(BaseModel):
    groups: List[GroupInfo] = Field(default_factory=list)
    inclusion: List[str] = Field(default_factory=list)
    exclusion: List[str] = Field(default_factory=list)


class EndpointsInfo(BaseModel):
    primary: Optional[str] = None
    secondary: List[str] = Field(default_factory=list)


class StatisticsInfo(BaseModel):
    software: Optional[str] = None  # e.g., R 4.3.2, SPSS 29
    alpha: float = 0.05
    methods: List[str] = Field(default_factory=list)  # tests/models e.g., Chi-square, Cox, PSM
    notes: Optional[str] = None


class TableFinding(BaseModel):
    statement: str
    values: Dict[str, Any] = Field(default_factory=dict)  # e.g., {"Robotic":"5%","Laparoscopic":"10%"}
    p_value: Optional[str] = None
    ci_95: Optional[str] = None


class TableData(BaseModel):
    id: str  # T1, T2...
    title: Optional[str] = None
    category: Optional[Literal["Baseline", "Perioperative", "Pathologic", "Oncologic", "Subgroup", "Other"]] = None
    header: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)  # stringified cells
    key_findings: List[TableFinding] = Field(default_factory=list)


class FigureData(BaseModel):
    id: str  # F1, F2...
    filename: str
    # Local path (server-side) for optional vision-based extraction.
    # Streamlit UI stores temp paths here.
    path: Optional[str] = None
    figure_type: Optional[Literal["KaplanMeier", "ForestPlot", "BarChart", "Other"]] = "Other"
    caption_raw: Optional[str] = None
    key_points: List[str] = Field(default_factory=list)


class StudyFactSheet(BaseModel):
    title: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    study_design: Optional[str] = None  # Retrospective cohort, RCT, etc.
    period: StudyPeriod = Field(default_factory=StudyPeriod)
    irb: IRBInfo = Field(default_factory=IRBInfo)
    population: PopulationInfo = Field(default_factory=PopulationInfo)
    endpoints: EndpointsInfo = Field(default_factory=EndpointsInfo)
    statistics: StatisticsInfo = Field(default_factory=StatisticsInfo)
    tables: List[TableData] = Field(default_factory=list)
    figures: List[FigureData] = Field(default_factory=list)
    protocol_key_points: List[str] = Field(default_factory=list)
    plan_text: Optional[str] = None  # extracted from proposal/protocol (for similarity checks)
    notes_for_writer: Optional[str] = None  # anything user wants to enforce


class Citation(BaseModel):
    pmid: Optional[str] = None
    doi: Optional[str] = None
    title: str
    authors: List[str] = Field(default_factory=list)
    journal: Optional[str] = None
    journal_iso_abbrev: Optional[str] = None
    year: Optional[int] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    publication_types: List[str] = Field(default_factory=list)  # RCT, Systematic Review, Guideline...
    url: Optional[str] = None
    abstract: Optional[str] = None


class CitationUse(BaseModel):
    citation: Citation
    use_for: List[Literal["Background", "Gap", "Methods", "Comparison", "Guideline", "Mechanism", "Other"]] = Field(default_factory=list)
    priority: int = 0  # higher = more preferred


class CitationPlan(BaseModel):
    max_count: int = 30
    selected: List[CitationUse] = Field(default_factory=list)


SectionName = Literal[
    "TitlePage",
    "Abstract",
    "Introduction",
    "Methods",
    "Results",
    "Discussion",
    "Conclusion",
    "References",
    "CoverLetter",
]


class SectionDraft(BaseModel):
    section: SectionName
    content: str
    locked: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Manuscript(BaseModel):
    journal: JournalSpec
    facts: StudyFactSheet
    citation_plan: CitationPlan
    drafts: Dict[SectionName, SectionDraft] = Field(default_factory=dict)
    assembled_main_text: Optional[str] = None
    assembled_references: List[str] = Field(default_factory=list)
