from __future__ import annotations

import json
import os
import tempfile
from typing import List, Dict

import streamlit as st

from auto_paper.models import JournalSpec, StudyFactSheet, CitationPlan, CitationUse, Citation, FigureData, TableData
from auto_paper.services.llm import OpenAIChatCompletionsClient, LLMError
from auto_paper.services.journal_guideline import fetch_guideline_text, build_journal_spec_with_llm
from auto_paper.services.ingest import (
    extract_text_from_docx,
    extract_text_from_pdf,
    parse_tables_from_docx,
    parse_tables_from_excel,
    infer_figure_type,
    build_fact_sheet_with_llm,
)
from auto_paper.services.citations_pubmed import suggest_citations, PubMedError
from auto_paper.services.section_writer import generate_section
from auto_paper.services.vancouver import assemble_main_text_and_references, number_drafts_and_build_references
from auto_paper.services.qa import run_qa
from auto_paper.services.similarity import similarity_report
from auto_paper.export.docx_exporter import export_manuscript_docx, export_cover_letter_docx


st.set_page_config(page_title="Auto Paper Writer (Clinical) MVP", layout="wide")

st.title("Auto Paper Writer (Clinical) — MVP")

# --- Session state init ---
def _init():
    st.session_state.setdefault("journal_spec", None)
    st.session_state.setdefault("guideline_text", "")
    st.session_state.setdefault("fact_sheet", None)
    st.session_state.setdefault("tables", [])
    st.session_state.setdefault("figures", [])
    st.session_state.setdefault("plan_text", "")
    st.session_state.setdefault("citation_candidates", [])
    st.session_state.setdefault("citation_plan", CitationPlan(max_count=30, selected=[]))
    st.session_state.setdefault("drafts", {})  # section -> {"content":..., "locked": bool}
_init()


# --- Sidebar: LLM settings ---
st.sidebar.header("LLM 설정")
api_key_input = st.sidebar.text_input("OPENAI_API_KEY (선택: .env 대신)", type="password")
model_input = st.sidebar.text_input("Model", value=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
base_url_input = st.sidebar.text_input("Base URL", value=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))

def get_llm():
    if api_key_input:
        os.environ["OPENAI_API_KEY"] = api_key_input
    if model_input:
        os.environ["OPENAI_MODEL"] = model_input
    if base_url_input:
        os.environ["OPENAI_BASE_URL"] = base_url_input
    return OpenAIChatCompletionsClient(api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL"), model=os.getenv("OPENAI_MODEL"))

# --- Step 1: Journal guideline ---
st.header("1) 저널 가이드라인 (Author Guidelines)")

col1, col2 = st.columns([2, 3])
with col1:
    journal_name = st.text_input("저널명", value=st.session_state.get("journal_name", ""))
    guideline_url = st.text_input("Author guideline URL", value=st.session_state.get("guideline_url", ""))

with col2:
    st.write("가이드라인을 URL에서 가져와 규정(JournalSpec)을 자동 추출합니다.")
    if st.button("가이드라인 가져오기 + JournalSpec 생성"):
        try:
            llm = get_llm()
            st.session_state["journal_name"] = journal_name
            st.session_state["guideline_url"] = guideline_url
            txt = fetch_guideline_text(guideline_url)
            st.session_state["guideline_text"] = txt
            spec = build_journal_spec_with_llm(llm, journal_name, guideline_url, txt)
            st.session_state["journal_spec"] = spec
            st.success("JournalSpec 생성 완료")
        except Exception as e:
            st.error(f"실패: {e}")

if st.session_state["journal_spec"] is not None:
    st.subheader("JournalSpec (JSON)")
    spec_json = st.session_state["journal_spec"].model_dump()
    st.json(spec_json)
    # Allow editing spec
    edited = st.text_area("JournalSpec 수정(고급): JSON을 직접 편집", value=json.dumps(spec_json, indent=2), height=220)
    if st.button("JournalSpec 수정 적용"):
        try:
            st.session_state["journal_spec"] = JournalSpec.model_validate(json.loads(edited))
            st.success("JournalSpec 업데이트 완료")
        except Exception as e:
            st.error(f"JSON 검증 실패: {e}")

# --- Step 2: Uploads ---
st.header("2) 파일 업로드 (계획서 + 결과표 + Figure)")

colA, colB, colC = st.columns(3)

with colA:
    st.subheader("연구계획서/프로토콜")
    plan_file = st.file_uploader("DOCX 또는 PDF 업로드", type=["docx", "pdf"], key="plan_uploader")
    if plan_file is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix="."+plan_file.name.split(".")[-1]) as tmp:
            tmp.write(plan_file.getbuffer())
            plan_path = tmp.name
        try:
            if plan_file.name.lower().endswith(".docx"):
                plan_text = extract_text_from_docx(plan_path)
            else:
                plan_text = extract_text_from_pdf(plan_path)
            st.session_state["plan_text"] = plan_text
            st.success(f"계획서 텍스트 추출 완료 (length={len(plan_text)})")
            st.text_area("추출된 텍스트(미리보기)", value=plan_text[:4000], height=200)
        except Exception as e:
            st.error(f"계획서 파싱 실패: {e}")

with colB:
    st.subheader("결과 Table")
    table_files = st.file_uploader("Word(DOCX) 또는 Excel(XLSX) 업로드 (복수 가능)", type=["docx", "xlsx"], accept_multiple_files=True, key="table_uploader")
    if table_files:
        tables: List[TableData] = []
        t_counter = 1
        for f in table_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix="."+f.name.split(".")[-1]) as tmp:
                tmp.write(f.getbuffer())
                path = tmp.name
            try:
                if f.name.lower().endswith(".docx"):
                    parsed = parse_tables_from_docx(path, prefix="T")
                else:
                    parsed = parse_tables_from_excel(path, prefix="T")
                # re-id sequentially across files
                for t in parsed:
                    t.id = f"T{t_counter}"
                    t_counter += 1
                    tables.append(t)
            except Exception as e:
                st.error(f"Table 파싱 실패({f.name}): {e}")
        st.session_state["tables"] = tables
        st.success(f"Table {len(tables)}개 파싱 완료")
        if tables:
            st.write("Table 미리보기(첫 번째)")
            st.json(tables[0].model_dump())

with colC:
    st.subheader("Figures")
    fig_files = st.file_uploader("Figure 업로드(PNG/JPG) (복수 가능)", type=["png", "jpg", "jpeg"], accept_multiple_files=True, key="fig_uploader")
    if fig_files:
        figures: List[FigureData] = []
        f_counter = 1
        for f in fig_files:
            with tempfile.NamedTemporaryFile(delete=False, suffix="."+f.name.split(".")[-1]) as tmp:
                tmp.write(f.getbuffer())
                path = tmp.name
            fig_type = infer_figure_type(f.name)
            figures.append(
                FigureData(
                    id=f"F{f_counter}",
                    filename=f.name,
                    path=path,
                    figure_type=fig_type,
                    caption_raw=None,
                )
            )
            f_counter += 1
        st.session_state["figures"] = figures
        st.success(f"Figure {len(figures)}개 등록 완료")
        if figures:
            st.write("Figure 미리보기")
            st.image(figures[0].path, caption=f"{figures[0].id}: {figures[0].filename}")
            st.json(figures[0].model_dump())

        # Optional captions input
        st.markdown("**(선택) Figure 캡션 입력** — 논문 본문 품질이 크게 좋아집니다.")
        for i, fig in enumerate(figures):
            cap = st.text_input(f"{fig.id} 캡션", value=fig.caption_raw or "", key=f"cap_{fig.id}")
            st.session_state["figures"][i].caption_raw = cap or None

# --- Step 3: FactSheet ---
st.header("3) FactSheet 생성 (StudyFactSheet)")

notes = st.text_input("작성자 추가 지시사항(선택)", value=st.session_state.get("notes_for_writer", ""))
vision_on = st.checkbox("Figure를 Vision으로 요약(권장)", value=True)

if st.button("FactSheet 생성 (LLM)"):
    try:
        llm = get_llm()
        if not st.session_state["plan_text"]:
            st.warning("계획서 텍스트가 비어 있습니다. (그래도 진행은 가능하지만 품질이 떨어집니다)")
        facts = build_fact_sheet_with_llm(
            llm_client=llm,
            plan_text=st.session_state["plan_text"] or "",
            tables=st.session_state["tables"],
            figures=st.session_state["figures"],
            notes_for_writer=notes or None,
            enable_vision_for_figures=vision_on,
        )
        st.session_state["fact_sheet"] = facts
        st.success("FactSheet 생성 완료")
    except LLMError as e:
        st.error(f"LLM 오류: {e}")
    except Exception as e:
        st.error(f"실패: {e}")

if st.session_state["fact_sheet"] is not None:
    st.subheader("StudyFactSheet (JSON)")
    fs_json = st.session_state["fact_sheet"].model_dump()
    st.json(fs_json)
    edited_fs = st.text_area("FactSheet 수정(권장): JSON 직접 편집", value=json.dumps(fs_json, indent=2), height=260)
    if st.button("FactSheet 수정 적용"):
        try:
            st.session_state["fact_sheet"] = StudyFactSheet.model_validate(json.loads(edited_fs))
            st.success("FactSheet 업데이트 완료")
        except Exception as e:
            st.error(f"JSON 검증 실패: {e}")

# --- Step 4: Citations ---
st.header("4) References 추천/선택 (PubMed)")

topic = st.text_input("PubMed 검색 토픽(예: rectal cancer robotic laparoscopic)", value=st.session_state.get("topic", ""))
intervention = st.text_input("Intervention(선택)", value=st.session_state.get("intervention", ""))
comparator = st.text_input("Comparator(선택)", value=st.session_state.get("comparator", ""))
outcomes = st.text_input("Outcomes(선택)", value=st.session_state.get("outcomes", ""))
years_recent = st.slider("최근 우선(년)", min_value=3, max_value=10, value=5)
retmax = st.slider("후보 수", min_value=20, max_value=100, value=40)
include_abs = st.checkbox("(선택) PubMed Abstract 포함(느리지만 Intro/Discussion 품질↑)", value=False)

if st.button("PubMed에서 후보 가져오기"):
    try:
        st.session_state["topic"] = topic
        st.session_state["intervention"] = intervention
        st.session_state["comparator"] = comparator
        st.session_state["outcomes"] = outcomes

        cands = suggest_citations(
            disease_or_topic=topic,
            intervention=intervention or None,
            comparator=comparator or None,
            outcomes=outcomes or None,
            years_recent=years_recent,
            retmax=retmax,
            include_abstracts=include_abs,
        )
        st.session_state["citation_candidates"] = cands
        st.success(f"후보 {len(cands)}개 가져옴")
    except PubMedError as e:
        st.error(f"PubMed 오류: {e}")
    except Exception as e:
        st.error(f"실패: {e}")

cands = st.session_state.get("citation_candidates", [])
if cands:
    st.subheader("후보 레퍼런스 선택 (최대 30개 권장)")
    options = []
    for c in cands:
        label = f"PMID:{c.pmid} | {c.year} | {c.journal_iso_abbrev or c.journal} | {c.title[:80]}"
        options.append(label)

    selected_labels = st.multiselect("선택", options=options, default=options[: min(15, len(options))])

    # Tagging controls (simple)
    default_use_for = st.multiselect(
        "선택한 문헌의 기본 용도 태그(선택)",
        options=["Background", "Gap", "Methods", "Comparison", "Guideline", "Mechanism", "Other"],
        default=["Background"],
    )

    if st.button("CitationPlan 업데이트(선택 반영)"):
        selected = []
        label_to_cit = {f"PMID:{c.pmid} | {c.year} | {c.journal_iso_abbrev or c.journal} | {c.title[:80]}": c for c in cands}
        for lab in selected_labels:
            c = label_to_cit.get(lab)
            if not c:
                continue
            selected.append(CitationUse(citation=Citation.model_validate(c.model_dump()), use_for=default_use_for, priority=0))
        st.session_state["citation_plan"] = CitationPlan(max_count=30, selected=selected)
        st.success(f"CitationPlan 설정 완료 (selected={len(selected)})")

if st.session_state.get("citation_plan") is not None:
    st.subheader("CitationPlan (JSON)")
    st.json(st.session_state["citation_plan"].model_dump())

# --- Step 5: Section generation (HITL) ---
st.header("5) 섹션별 생성 + 수정/확정 (Human-in-the-loop)")

if st.session_state["journal_spec"] is None or st.session_state["fact_sheet"] is None:
    st.info("JournalSpec과 FactSheet를 먼저 생성하세요.")
else:
    sec = st.selectbox("생성할 섹션", ["Methods", "Results", "Introduction", "Discussion", "Conclusion", "Abstract", "CoverLetter"])
    override = st.text_area("이번 섹션에만 적용할 추가 지시사항(선택)", value="")
    two_pass = st.checkbox("2-pass 모드(뼈대→본문)로 생성", value=True)

    colg1, colg2 = st.columns([1,1])
    with colg1:
        if st.button("섹션 생성(LLM)"):
            try:
                llm = get_llm()
                txt = generate_section(
                    llm_client=llm,
                    section=sec if sec != "CoverLetter" else "CoverLetter",
                    journal=st.session_state["journal_spec"],
                    facts=st.session_state["fact_sheet"],
                    citation_plan=st.session_state["citation_plan"],
                    user_overrides=override or None,
                    two_pass=two_pass,
                )
                st.session_state["drafts"].setdefault(sec, {"content": "", "locked": False})
                st.session_state["drafts"][sec]["content"] = txt
                st.session_state["drafts"][sec]["locked"] = False
                st.success(f"{sec} 생성 완료")
            except Exception as e:
                st.error(f"실패: {e}")

    with colg2:
        if st.button("현재 섹션 잠금/해제 토글"):
            st.session_state["drafts"].setdefault(sec, {"content": "", "locked": False})
            st.session_state["drafts"][sec]["locked"] = not st.session_state["drafts"][sec]["locked"]

    st.subheader("섹션 초안 편집")
    st.session_state["drafts"].setdefault(sec, {"content": "", "locked": False})
    locked = st.session_state["drafts"][sec]["locked"]
    content = st.text_area(
        f"{sec} 내용({'LOCKED' if locked else 'editable'})",
        value=st.session_state["drafts"][sec]["content"],
        height=300,
        disabled=locked,
    )
    if not locked:
        st.session_state["drafts"][sec]["content"] = content

# --- Step 6: Assemble + QA + Similarity ---
st.header("6) 최종 병합 + QA + 표절/중복(로컬) 검사")

if st.session_state["journal_spec"] is None:
    st.info("JournalSpec이 필요합니다.")
else:
    include_abs = st.checkbox("Abstract의 인용도 Vancouver 번호에 포함", value=False)

    if st.button("Assemble (Vancouver 재번호화 + References 생성)"):
        drafts_map = {k: v["content"] for k, v in st.session_state["drafts"].items() if v.get("content")}
        numbered_drafts, refs = number_drafts_and_build_references(
            journal=st.session_state["journal_spec"],
            drafts=drafts_map,
            citation_plan=st.session_state["citation_plan"],
            include_abstract_citations=include_abs,
        )
        assembled, _refs2 = assemble_main_text_and_references(
            journal=st.session_state["journal_spec"],
            drafts=drafts_map,
            citation_plan=st.session_state["citation_plan"],
            include_abstract_citations=include_abs,
        )
        st.session_state["numbered_drafts"] = numbered_drafts
        st.session_state["assembled_text"] = assembled
        st.session_state["assembled_refs"] = refs
        st.success(f"Assemble 완료 (refs={len(refs)})")

    if st.session_state.get("assembled_text"):
        st.subheader("Assembled Main Text (preview)")
        st.text_area("main text", value=st.session_state["assembled_text"][:8000], height=260)
    if st.session_state.get("assembled_refs"):
        st.subheader("References")
        st.write("\n".join(st.session_state["assembled_refs"]))

    if st.button("QA 실행"):
        drafts_map = {k: v["content"] for k, v in st.session_state["drafts"].items() if v.get("content")}
        report = run_qa(
            journal=st.session_state["journal_spec"],
            facts=st.session_state["fact_sheet"] if st.session_state["fact_sheet"] else StudyFactSheet(),
            drafts=drafts_map,
            assembled_references=st.session_state.get("assembled_refs"),
            citations_numbered=False,
        )
        st.session_state["qa_report"] = report
        st.success("QA 완료")

    if st.session_state.get("qa_report"):
        st.subheader("QA Report")
        st.json(st.session_state["qa_report"])

    if st.button("로컬 유사도(중복/자기표절) 검사"):
        gen = {k: v["content"] for k, v in st.session_state["drafts"].items() if v.get("content")}
        src = {}
        if st.session_state.get("plan_text"):
            src["Protocol/Plan"] = st.session_state["plan_text"]
        if st.session_state.get("guideline_text"):
            src["JournalGuideline"] = st.session_state["guideline_text"]
        results = similarity_report(gen, src, threshold=0.12)
        st.session_state["sim_results"] = [r.__dict__ for r in results]
        st.success("검사 완료")

    if st.session_state.get("sim_results") is not None:
        st.subheader("Similarity Findings (above threshold)")
        st.json(st.session_state["sim_results"])

# --- Step 7: Export DOCX ---
st.header("7) DOCX Export")

if st.session_state.get("assembled_refs") and st.session_state["journal_spec"] is not None:
    title = st.text_input("논문 제목(선택)", value=(st.session_state["fact_sheet"].title if st.session_state["fact_sheet"] else ""))

    if st.button("DOCX 파일 생성"):
        drafts_map = {k: v["content"] for k, v in st.session_state["drafts"].items() if v.get("content")}
        # Use numbered drafts (with [n]) if available.
        numbered = st.session_state.get("numbered_drafts") or {}
        export_drafts = drafts_map.copy()
        # overwrite IMRaD + Abstract with numbered text
        for k, v in numbered.items():
            export_drafts[k] = v
        out_dir = tempfile.mkdtemp()
        manuscript_path = os.path.join(out_dir, "Manuscript.docx")
        cover_path = os.path.join(out_dir, "Cover_Letter.docx")

        export_manuscript_docx(
            output_path=manuscript_path,
            journal=st.session_state["journal_spec"],
            drafts=export_drafts,
            references=st.session_state["assembled_refs"],
            title=title or None,
        )

        if drafts_map.get("CoverLetter"):
            export_cover_letter_docx(
                output_path=cover_path,
                journal=st.session_state["journal_spec"],
                cover_letter_text=drafts_map["CoverLetter"],
            )

        st.session_state["manuscript_path"] = manuscript_path
        st.session_state["cover_path"] = cover_path
        st.success("DOCX 생성 완료")

    if st.session_state.get("manuscript_path") and os.path.exists(st.session_state["manuscript_path"]):
        with open(st.session_state["manuscript_path"], "rb") as f:
            st.download_button("Manuscript.docx 다운로드", f, file_name="Manuscript.docx")
    if st.session_state.get("cover_path") and os.path.exists(st.session_state["cover_path"]):
        with open(st.session_state["cover_path"], "rb") as f:
            st.download_button("Cover_Letter.docx 다운로드", f, file_name="Cover_Letter.docx")
else:
    st.info("Assemble을 먼저 실행해 References를 만든 뒤 DOCX Export가 가능합니다.")
