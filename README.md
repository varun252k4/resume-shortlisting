# Resume Shortlisting

AI resume shortlisting system with:

- Resume upload + structured parsing (PDF / DOCX / TXT)
- JD analysis from free-text
- Weighted scoring (0–100) and ranking
- Match flagging (`Strong Match`, `Moderate Match`, `Does Not Meet Requirements`)
- Resume shortlist thresholding
- Employer feedback loop for calibration

---

## Prerequisites

- Python 3.9+ (3.13 recommended)
- Git
- An LLM API key for resume extraction / optional summaries (Groq, OpenAI, etc.)

---

## Setup

1. Clone and enter the repo:

```bash
git clone https://github.com/varun252k4/resume-shortlisting.git
cd resume-shortlisting
```

2. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependencies:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

4. Configure `.env`:

```env
LLM_MODEL=groq/qwen/qwen3-32b
LLM_API_KEY=your_llm_api_key
CHROMA_PATH=./chroma_db
EMBED_MODEL=BAAI/bge-small-en-v1.5
```

> Replace `your_llm_api_key` with your real key.  
> Keep keys out of shared logs/screenshots.

---

## APIs in this repo

This project exposes two apps:

1. `resume_parser` (parser-only service)
2. `scorer` (parser + scoring + feedback service)

You can run either one based on your use case.

### Option A: Run full scoring app (recommended)

Includes parse + scoring endpoints.

```bash
python3 -m uvicorn scorer.main:app --reload --port 8000
```

Open in browser:

```
http://127.0.0.1:8000/docs
```

### Option B: Run parser-only app

If you only need extraction:

```bash
python3 -m uvicorn resume_parser.main:app --reload --port 8010
```

Docs:

```
http://127.0.0.1:8010/docs
```

---

## Parsing API (parser endpoints)

Used by both parser and scorer apps in this codebase.

### Health

- `GET /health`

### Parse one resume

- `POST /parse`
- `multipart/form-data` field name: `file`
- Max: PDF / DOCX / DOC / TXT

Example:

```bash
curl -X POST http://127.0.0.1:8000/parse \
  -F "file=@/Users/vedank.wakalkar/Desktop/College_Work/resume-shortlisting/Vedank_VIIT_Resume.pdf"
```

### Parse batch

- `POST /parse/batch`
- File input: `files`
- Supports up to 500 resumes in one request

---

## Scoring API (in `scorer.main`)

### Score one candidate

- `POST /score`
- Body includes:
  - `resume` (parsed resume JSON)
  - `jd_text` or `requirements`
  - optional `weightage`
  - optional `shortlist_threshold`
  - optional `use_ai_summary`

### Score multiple candidates

- `POST /score/batch`
- Same payload as above, but with `resumes: [...]`
- Returns ranked list (adds `rank`), sorted by score desc.

### JD helper

- `POST /jd/analyze` (body: `{ "jd_text": "..." }`)  
  returns extracted structured requirements.

### Feedback loop

- `POST /feedback` with `FeedbackRequest`
- `GET /feedback/status/{jd_id}`

---

## Quick Troubleshooting

If you see `Errno 48: Address already in use`:

```bash
lsof -iTCP:8000 -sTCP:LISTEN -n -P
kill <PID>
```

or use a different port:

```bash
python3 -m uvicorn scorer.main:app --reload --port 8001
```

---

## Supported file types

- PDF (`.pdf`)
- Word (`.docx`, `.doc`)
- Text (`.txt`)

---

## Notes

- ChromaDB data is stored in `chroma_db/`.
- This project supports up to 500 resumes in batch endpoints.
