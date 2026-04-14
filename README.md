# Resume Shortlisting

An AI-powered resume screening backend. Upload resumes (PDF / DOCX / TXT), parse them into structured JSON, score them against a Job Description using vector similarity, and shortlist candidates — all through a single FastAPI server.

---

## Requirements

- [Python 3.13+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — fast Python package manager
- An LLM API key (Groq, OpenAI, Anthropic, Mistral, or any provider supported by [litellm](https://docs.litellm.ai/))

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/varun252k4/resume-shortlisting.git
cd resume-shortlisting
```

### 2. Create and activate the virtual environment

```bash
uv venv
```

Activate it:

- **Windows (PowerShell)**
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Windows (CMD)**
  ```cmd
  .venv\Scripts\activate.bat
  ```
- **macOS / Linux**
  ```bash
  source .venv/bin/activate
  ```

### 3. Install dependencies

```bash
uv sync
```

### 4. Configure environment

Create a `scorer/.env` file (or export these variables in your shell):

```env
# ── Required ──────────────────────────────────────────────────────────────
LLM_API_KEY=your_api_key_here

# ── LLM provider (pick one) ───────────────────────────────────────────────
LLM_MODEL=groq/qwen/qwen3-32b          # Groq  (default)
# LLM_MODEL=openai/gpt-4o              # OpenAI
# LLM_MODEL=anthropic/claude-3-haiku-20240307  # Anthropic
# LLM_MODEL=ollama/llama3              # Local Ollama

# ── Optional tuning ───────────────────────────────────────────────────────
MAX_TOKENS=1024                         # LLM response tokens for extraction
EMBED_MODEL=BAAI/bge-small-en-v1.5     # fastembed model (runs locally, no key needed)
CHROMA_PATH=./chroma_db                 # ChromaDB storage path
JWT_SECRET=replace-this-please          # JWT signing secret (change in production)
JWT_EXPIRES_MINUTES=1440                # Token validity in minutes (default: 24 h)
```

> **Tip:** Groq offers a generous free tier. Get a key at [console.groq.com](https://console.groq.com/).

---

## Running the Server

Start the unified FastAPI server from the **project root**:

```bash
uvicorn main:app --reload
```

The API is available at `http://localhost:8000`.  
Interactive Swagger docs: `http://localhost:8000/docs`

---

## API Reference

### Base URL
```
http://localhost:8000
```

---

### System

| Method | Endpoint   | Auth | Description   |
|--------|------------|------|---------------|
| GET    | `/health`  | No   | Health check  |

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

### Authentication

All protected endpoints require a Bearer token obtained from `/auth/signup` or `/auth/login`.

```
Authorization: Bearer <token>
```

#### Sign up

```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Jane Recruiter",
    "email": "jane@company.com",
    "password": "secret123",
    "role": "employer"
  }'
```

Valid roles: `"employer"` (recruiter) · `"employee"` (candidate)

**Response**
```json
{
  "success": true,
  "token": "<jwt>",
  "user": { "id": "...", "name": "Jane Recruiter", "email": "jane@company.com", "role": "employer" }
}
```

#### Log in

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{ "email": "jane@company.com", "password": "secret123" }'
```

#### Current user

```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <token>"
```

---

### Resume Parsing

Parse resumes into structured JSON without scoring them. No authentication required.

#### Parse a single resume

```bash
curl -X POST http://localhost:8000/parse \
  -F "file=@/path/to/resume.pdf"
```

**Response**
```json
{
  "success": true,
  "filename": "resume.pdf",
  "parse_time_seconds": 2.1,
  "data": {
    "name": "John Smith",
    "contact": {
      "email": "john@example.com",
      "phone": "+1-555-0100",
      "location": "New York, USA",
      "linkedin": "https://linkedin.com/in/johnsmith"
    },
    "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "work_experience": [
      {
        "company": "Acme Corp",
        "role": "Senior Backend Engineer",
        "duration": "Jan 2021 – Present",
        "description": "Built microservices handling 50k req/s."
      }
    ],
    "education": [
      { "institution": "MIT", "degree": "B.Sc. Computer Science", "year": "2019" }
    ],
    "certifications": ["AWS Solutions Architect"],
    "raw_text": "..."
  }
}
```

Supported file types: **PDF**, **DOCX**, **DOC**, **TXT** · Max size: **10 MB**

#### Parse multiple resumes (batch)

```bash
curl -X POST http://localhost:8000/parse/batch \
  -F "files=@resume1.pdf" \
  -F "files=@resume2.docx" \
  -F "files=@resume3.txt"
```

Returns an array of `ParseResponse` objects. Up to **500 files** per call.

---

### Scoring

Score one or more parsed resumes against a Job Description. Returns a 0–100 score, a match flag, and a summary.

#### Weightage configuration

Every scoring endpoint accepts a `weightage` object to control how much each dimension contributes to the final score. Values must sum to **1.0**.

```json
{
  "skills": 0.40,
  "experience": 0.30,
  "education": 0.20,
  "certifications": 0.10
}
```

Default weights if omitted: skills 40 % · experience 30 % · education 20 % · certifications 10 %.

#### Score a single resume

```bash
curl -X POST http://localhost:8000/score \
  -H "Content-Type: application/json" \
  -d '{
    "resume": {
      "name": "John Smith",
      "skills": ["Python", "FastAPI", "PostgreSQL"],
      "work_experience": [
        { "company": "Acme Corp", "role": "Backend Engineer", "duration": "2021-Present", "description": "..." }
      ],
      "education": [
        { "institution": "MIT", "degree": "B.Sc. Computer Science", "year": "2019" }
      ],
      "certifications": ["AWS Solutions Architect"],
      "contact": {}
    },
    "jd_text": "We are looking for a Senior Python Backend Engineer with 3+ years experience in FastAPI and PostgreSQL...",
    "weightage": {
      "skills": 0.50,
      "experience": 0.30,
      "education": 0.10,
      "certifications": 0.10
    },
    "shortlist_threshold": 60.0,
    "use_ai_summary": true
  }'
```

**Response**
```json
{
  "success": true,
  "score_time_seconds": 1.8,
  "result": {
    "candidate_name": "John Smith",
    "jd_id": "abc123def456",
    "resume_id": "xyz789",
    "total_score": 82.5,
    "raw_total_score": 82.5,
    "calibration_offset": 0.0,
    "feedback_applied": false,
    "breakdown": {
      "skills": 88.0,
      "experience": 79.0,
      "education": 70.0,
      "certifications": 85.0
    },
    "flag": "Strong Match",
    "summary": "John Smith scored 82.5/100 ...",
    "matched_skills": ["Python", "FastAPI", "PostgreSQL"],
    "missing_skills": ["Redis", "Kubernetes"],
    "is_shortlisted": true,
    "rank": null
  }
}
```

Match flags: `"Strong Match"` (≥75) · `"Moderate Match"` (≥50) · `"Does Not Meet Requirements"` (<50)

#### Score multiple resumes (batch)

```bash
curl -X POST http://localhost:8000/score/batch \
  -H "Content-Type: application/json" \
  -d '{
    "resumes": [ { "name": "Alice", "skills": ["Python"], ... }, { ... } ],
    "jd_text": "Senior Python Engineer...",
    "weightage": { "skills": 0.40, "experience": 0.30, "education": 0.20, "certifications": 0.10 },
    "shortlist_threshold": 50.0,
    "use_ai_summary": false
  }'
```

Returns an array of `ScoreResponse` objects sorted by score descending, with `rank` assigned.  
Up to **500 resumes** per call.

---

### End-to-End Batch Shortlisting

Upload raw resume files and a JD text together — parsing, scoring, and ranking happen in one call.

```bash
curl -X POST http://localhost:8000/shortlist/batch \
  -F "files=@resume1.pdf" \
  -F "files=@resume2.pdf" \
  -F "jd_text=We are looking for a Senior Python Engineer with FastAPI experience..." \
  -F "weightage_skills=0.50" \
  -F "weightage_experience=0.30" \
  -F "weightage_education=0.10" \
  -F "weightage_certifications=0.10" \
  -F "shortlist_threshold=60" \
  -F "use_ai_summary=false"
```

| Form field                   | Type    | Default | Description                                              |
|------------------------------|---------|---------|----------------------------------------------------------|
| `files`                      | file(s) | —       | Resume files (PDF / DOCX / TXT), multi-file              |
| `jd_text`                    | string  | —       | Raw job description text                                 |
| `weightage_skills`           | float   | 0.40    | Skills weight (all four must sum to 1.0)                 |
| `weightage_experience`       | float   | 0.30    | Experience weight                                        |
| `weightage_education`        | float   | 0.20    | Education weight                                         |
| `weightage_certifications`   | float   | 0.10    | Certifications weight                                    |
| `shortlist_threshold`        | float   | 50.0    | Minimum score to mark `is_shortlisted=true`              |
| `use_ai_summary`             | bool    | false   | Generate LLM narrative summary (slower; disable for speed) |

**Response**
```json
{
  "total": 2,
  "shortlisted": 1,
  "candidates": [
    {
      "filename": "resume1.pdf",
      "parse_success": true,
      "score_success": true,
      "result": { "total_score": 78.2, "flag": "Strong Match", "rank": 1, "is_shortlisted": true, ... },
      "total_time_seconds": 3.1
    },
    {
      "filename": "resume2.pdf",
      "parse_success": true,
      "score_success": true,
      "result": { "total_score": 44.6, "flag": "Does Not Meet Requirements", "rank": 2, "is_shortlisted": false, ... },
      "total_time_seconds": 2.8
    }
  ]
}
```

---

### Job Description Analysis

Extract structured signals (required skills, experience level, qualifications) from raw JD text without running the full scorer.

```bash
curl -X POST http://localhost:8000/jd/analyze \
  -H "Content-Type: application/json" \
  -d '{ "jd_text": "We are looking for a Senior Python Engineer with 5+ years..." }'
```

**Response**
```json
{
  "success": true,
  "raw_text": "We are looking for ...",
  "requirements": {
    "required_skills": ["Python", "FastAPI"],
    "preferred_skills": ["Docker", "Kubernetes"],
    "required_experience_years": 5.0,
    "qualifications": ["B.Sc. Computer Science"],
    "role_keywords": ["Senior Python Engineer"]
  }
}
```

---

### Recruitment Workflow (Employer)

These endpoints require an `employer` role JWT token.

#### Create a job posting

```bash
curl -X POST http://localhost:8000/employer/jobs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Senior Python Engineer",
    "jd_text": "We are looking for a Senior Python Engineer with 5+ years..."
  }'
```

#### List your jobs

```bash
curl http://localhost:8000/employer/jobs \
  -H "Authorization: Bearer <token>"
```

#### Rank uploaded resumes against a job

```bash
curl -X POST http://localhost:8000/employer/jobs/<job_id>/rank \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "resume_ids": ["<resume_id_1>", "<resume_id_2>"],
    "weightage": {
      "skills": 0.45,
      "experience": 0.30,
      "education": 0.15,
      "certifications": 0.10
    },
    "shortlist_threshold": 60.0,
    "use_ai_summary": false
  }'
```

`resume_ids` is optional — omit it to rank **all** uploaded resumes.  
`requirements` can also be passed to override/supplement skills extracted from the JD text.

#### Get stored rankings

```bash
curl http://localhost:8000/employer/jobs/<job_id>/rankings \
  -H "Authorization: Bearer <token>"
```

---

### Candidate Resumes

These endpoints require a `candidate` (employee) role JWT token.

#### Upload resumes

```bash
curl -X POST http://localhost:8000/candidate/resumes \
  -H "Authorization: Bearer <token>" \
  -F "files=@my_resume.pdf"
```

Resume is parsed on upload and stored with the user's account. Supports multiple files.

#### List my resumes

```bash
curl http://localhost:8000/candidate/resumes \
  -H "Authorization: Bearer <token>"
```

---

### Feedback & Calibration

Employers can submit corrections to improve future scoring accuracy for a given JD. The mean offset (employer score − AI score) is stored and automatically applied on subsequent calls.

#### Submit feedback

```bash
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "jd_id": "abc123def456",
    "resume_id": "xyz789",
    "resume_name": "John Smith",
    "ai_total_score": 82.5,
    "employer_total_score": 75.0,
    "ai_flag": "Strong Match",
    "employer_flag": "Moderate Match"
  }'
```

#### Check calibration state

```bash
curl http://localhost:8000/feedback/status/abc123def456
```

**Response**
```json
{
  "success": true,
  "calibration": {
    "feedback_count": 3,
    "feedback_alignment_pct": 66.7,
    "calibration_offset": -4.5,
    "last_recalibrated_at": "2026-04-14T10:00:00+00:00"
  }
}
```

---

## Endpoint Summary

| Method | Endpoint                                | Auth          | Description                                    |
|--------|-----------------------------------------|---------------|------------------------------------------------|
| GET    | `/health`                               | No            | Server health check                            |
| POST   | `/auth/signup`                          | No            | Register a new user                            |
| POST   | `/auth/login`                           | No            | Log in, receive JWT                            |
| GET    | `/auth/me`                              | Bearer        | Current user info                              |
| POST   | `/parse`                                | No            | Parse a single resume file                     |
| POST   | `/parse/batch`                          | No            | Parse up to 500 resume files                   |
| POST   | `/score`                                | No            | Score one parsed resume against a JD           |
| POST   | `/score/batch`                          | No            | Score up to 500 parsed resumes against a JD    |
| POST   | `/shortlist/batch`                      | No            | Upload files + JD → parse + score + rank       |
| POST   | `/jd/analyze`                           | No            | Extract structured signals from JD text        |
| POST   | `/feedback`                             | No            | Submit employer score correction               |
| GET    | `/feedback/status/{jd_id}`             | No            | Get calibration state for a JD                 |
| POST   | `/employer/jobs`                        | Employer JWT  | Create a job posting                           |
| GET    | `/employer/jobs`                        | Employer JWT  | List your job postings                         |
| POST   | `/employer/jobs/{job_id}/rank`          | Employer JWT  | Rank stored resumes against a job              |
| GET    | `/employer/jobs/{job_id}/rankings`      | Employer JWT  | Retrieve stored ranking results                |
| POST   | `/candidate/resumes`                    | Candidate JWT | Upload and parse resumes                       |
| GET    | `/candidate/resumes`                    | Candidate JWT | List uploaded resumes                          |

---

## Project Structure

```
resume-shortlisting/
├── main.py               # Unified FastAPI entry point (run this)
├── pyproject.toml
├── requirements.txt
├── chroma_db/            # ChromaDB vector storage (auto-created)
├── data/
│   └── app_store.json    # Users, jobs, resumes, rankings (auto-created)
├── parser/
│   ├── parser.py         # Raw text extraction (PDF / DOCX / TXT)
│   └── extractor.py      # LLM field extraction
├── scorer/
│   ├── config.py         # Environment variable configuration
│   ├── models.py         # All Pydantic models
│   ├── scorer.py         # Scoring orchestrator
│   ├── jd_parser.py      # Heuristic JD signal extraction
│   ├── vector_store.py   # ChromaDB indexing & similarity queries
│   ├── embedder.py       # fastembed local embeddings
│   └── feedback_store.py # Calibration persistence
└── frontend/             # React frontend (optional)
```

## Quick Test Script

To test the parser directly (no server needed):

```bash
python test.py
```

This extracts text from `Varun_Vangar_Resume.pdf` and prints the structured JSON output.

---

## Supported File Types

- PDF (`.pdf`)
- Word Document (`.docx`, `.doc`)
- Plain Text (`.txt`)
