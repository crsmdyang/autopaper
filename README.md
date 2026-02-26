# Auto Paper Writer (Clinical Manuscript) — MVP Skeleton

임상/의학 SCI 원저(Original Article) 작성 자동화를 위한 **실행 가능한 MVP 코드 스켈레톤**입니다.

## 무엇을 해주나 (MVP)
- 저널 Author Guideline URL을 받아서 **규정(JournalSpec)** 을 JSON으로 추출(LLM 사용)
- 연구계획서(Word/PDF) + 결과 Table(Word/Excel) + Figure(이미지)를 업로드 → **팩트시트(StudyFactSheet)** 생성(LLM 사용, 모르는 값은 null)
  - Table: 원본 표(헤더/셀)를 **그대로 보존** + LLM으로 category/key_findings 자동 추출
  - Figure: (선택) Vision 입력으로 key points 추출(캡션만으로도 가능)
- PubMed 기반으로 레퍼런스 후보를 검색/가져오기(선택: 인터넷 필요) → 사용자가 최종 ≤30개 확정
- 섹션별(Methods→Results→Intro→Discussion→Conclusion→Abstract→Cover letter)로 생성
  - 생성 후 사용자가 **수정/확정(락)** 하는 Human-in-the-loop 흐름
  - 기본은 **2-pass(뼈대→본문)**: 업로드된 plan/table/figure로 outline을 먼저 만든 뒤, 선택한 참고문헌으로 살을 붙임
- 인용은 `{cite:PMID:xxxx}` 플레이스홀더로 찍고,
  최종 Assemble 단계에서 **Vancouver 번호를 최초 등장 순서대로 재번호화**
- 품질검사(QA): 단어 수, 구조(Structured Abstract), 레퍼런스 개수(≤30), cite 누락 경고
- 내부 표절/중복 검사(로컬 유사도): 
  - (1) 생성된 텍스트 vs 업로드 계획서
  - (2) 생성된 텍스트 vs 저널 가이드라인 텍스트
  - (3) 섹션 간 중복

> ⚠️ 외부 학술DB 전체와 비교하는 “출판급 표절검사”는 iThenticate 계정/API가 필요합니다.  
> 이 레포는 **커넥터(인터페이스)** 를 제공하고, 실제 호출은 사용자가 키/계정을 넣어 활성화하도록 했습니다.

---

## 빠른 시작 (Streamlit UI)
### 1) 설치
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 2) 환경변수(.env)
- `OPENAI_API_KEY` : LLM 호출에 사용 (예시로 OpenAI Chat Completions 방식 포함)
- `OPENAI_MODEL` : 기본 `gpt-4.1-mini` (원하면 변경)
- `USER_AGENT_EMAIL` : PubMed Entrez 호출 시 권장(예: you@example.com)

### 3) 실행
```bash
streamlit run app_streamlit.py
```

---

## 선택: FastAPI 서버로 실행
```bash
uvicorn api.main:app --reload --port 8000
```

---

## 폴더 구조
- `auto_paper/models.py` : Pydantic 스키마 (JournalSpec/StudyFactSheet/CitationPlan 등)
- `auto_paper/services/` :
  - `llm.py` : LLM 어댑터(OpenAI 예시 포함) — 다른 모델로 교체 가능
  - `journal_guideline.py` : 가이드라인 크롤링/텍스트 추출/JournalSpec 생성
  - `ingest.py` : Word/Excel Table 파싱, 계획서 텍스트 추출
  - `citations_pubmed.py` : PubMed 검색/메타데이터 가져오기
  - `section_writer.py` : 섹션별 작성(프롬프트 템플릿 포함)
  - `vancouver.py` : 플레이스홀더 → Vancouver 번호 재부여 + Reference 리스트 생성
  - `qa.py` : 규정/구조/word count/cite 누락 검사
  - `similarity.py` : 로컬 유사도(중복/자기표절) 검사
- `auto_paper/export/docx_exporter.py` : 최종 DOCX 생성(python-docx)

---

## 주의 / 윤리
- 숫자/결과는 **LLM이 새로 만들면 안 됩니다.**  
  이 코드는 Table에서 파싱된 수치를 “팩트시트”로 고정하고, 생성 시 그 범위 밖 숫자 사용을 금지하도록 설계했습니다.
- AI 사용 고지/저자 책임은 저널 정책이 다릅니다. ICMJE는 AI 사용 공개를 권고합니다.

---

## 다음 확장 포인트
- JournalSpec을 출판사(Elsevier/Springer/Nature/MDPI 등)별로 템플릿 캐시
- STROBE/CONSORT/PRISMA 체크리스트 기반 누락 항목 자동 경고
- iThenticate API 연동(계정 필요)
