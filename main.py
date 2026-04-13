"""
Unified FastAPI entry point.

Run with:
    uvicorn main:app --reload

All routes (parse, score, JD analysis, feedback) are served from this single app.
"""

# ── sys.path must be configured BEFORE any local imports ──────────────────
import sys
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))

# scorer/ must come BEFORE parser/ so scorer/models.py (which contains all
# scoring models) takes precedence over parser/models.py for flat imports.
sys.path.insert(0, os.path.join(_ROOT, "parser"))
sys.path.insert(0, os.path.join(_ROOT, "scorer"))

# ── Stdlib / third-party ──────────────────────────────────────────────────
import asyncio
import time
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Local modules (resolved via sys.path set above) ───────────────────────
from feedback_store import add_feedback_record, get_calibration
from models import (
    BatchScoreRequest,
    ContactInfo,
    Education,
    FeedbackRequest,
    ParsedResume,
    ParseResponse,
    ScoreRequest,
    ScoreResponse,
    WeightageConfig,
    WorkExperience,
)
from parser import clean_text, extract_raw_text  # parser/parser.py
from extractor import extract_fields              # parser/extractor.py
from scorer import score_candidate               # scorer/scorer.py
from jd_parser import parse_job_description      # scorer/jd_parser.py

# ── App ────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="AI Resume Screening API",
    description=(
        "Parse resumes (PDF/DOCX/TXT), extract structured data, score candidates "
        "against a Job Description, and shortlist at scale."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "txt"}
MAX_FILE_SIZE_MB = 10


# ── Health ─────────────────────────────────────────────────────────────────


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}


# ── Resume Parsing ─────────────────────────────────────────────────────────


async def _parse_file(filename: str, file_bytes: bytes) -> ParseResponse:
    """Shared helper used by single and batch parse endpoints."""
    start = time.time()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return ParseResponse(
            success=False,
            filename=filename,
            error=f"Unsupported file type '.{ext}'. Allowed: PDF, DOCX, TXT.",
        )
    if len(file_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
        return ParseResponse(
            success=False,
            filename=filename,
            error=f"File exceeds {MAX_FILE_SIZE_MB} MB limit.",
        )
    try:
        raw_text = extract_raw_text(filename, file_bytes)
        raw_text = clean_text(raw_text)
        if not raw_text.strip():
            raise ValueError("No readable text found in the document.")
        extracted = await extract_fields(raw_text)
        parsed = ParsedResume(
            name=extracted.get("name"),
            contact=ContactInfo(**extracted.get("contact", {})),
            skills=extracted.get("skills", []),
            work_experience=[WorkExperience(**e) for e in extracted.get("work_experience", [])],
            education=[Education(**e) for e in extracted.get("education", [])],
            certifications=extracted.get("certifications", []),
            raw_text=raw_text,
        )
        return ParseResponse(
            success=True,
            filename=filename,
            data=parsed,
            parse_time_seconds=round(time.time() - start, 2),
        )
    except Exception as exc:
        return ParseResponse(success=False, filename=filename, error=str(exc))


@app.post("/parse", response_model=ParseResponse, tags=["Parsing"])
async def parse_resume(file: UploadFile = File(...)):
    """
    Upload a single resume (PDF, DOCX, or TXT) and receive structured JSON.
    Target latency: under 5 seconds per document.
    """
    file_bytes = await file.read()
    return await _parse_file(file.filename, file_bytes)


@app.post("/parse/batch", response_model=list[ParseResponse], tags=["Parsing"])
async def parse_batch(files: list[UploadFile] = File(...)):
    """
    Upload up to 500 resumes and parse them concurrently.
    Target: up to 500 resumes within 3 minutes.
    """
    if len(files) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 resumes per batch.")
    payloads = [(f.filename, await f.read()) for f in files]
    return list(await asyncio.gather(*[_parse_file(fn, fb) for fn, fb in payloads]))


# ── Scoring ────────────────────────────────────────────────────────────────


@app.post("/score", response_model=ScoreResponse, tags=["Scoring"])
async def score_single(body: ScoreRequest):
    """
    Score one parsed resume against a Job Description.

    - Pass ``jd_text`` (raw JD string) or ``requirements`` (structured fields),
      or both — they will be merged.
    - JD embeddings are cached in ChromaDB; repeated calls with the same JD text
      incur no re-embedding cost.
    - Optionally set custom ``weightage`` to prioritise skills over experience etc.
    - Returns a 0–100 score, a flag (Strong / Moderate / Does Not Meet), and an
      AI-written summary explaining the match.
    """
    start = time.time()
    try:
        result = await score_candidate(
            body.resume,
            body.jd_text,
            body.weightage,
            requirements=body.requirements,
            use_ai_summary=body.use_ai_summary,
            shortlist_threshold=body.shortlist_threshold,
        )
        return ScoreResponse(
            success=True,
            result=result,
            score_time_seconds=round(time.time() - start, 2),
        )
    except Exception as exc:
        return ScoreResponse(success=False, error=str(exc))


@app.post("/score/batch", response_model=list[ScoreResponse], tags=["Scoring"])
async def score_batch(body: BatchScoreRequest):
    """
    Score up to 500 resumes against the same JD concurrently.
    Results are sorted by score descending and assigned a rank.
    """
    if len(body.resumes) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 resumes per batch.")

    async def _score_one(resume: ParsedResume) -> ScoreResponse:
        t = time.time()
        try:
            result = await score_candidate(
                resume,
                body.jd_text,
                body.weightage,
                requirements=body.requirements,
                use_ai_summary=body.use_ai_summary,
                shortlist_threshold=body.shortlist_threshold,
            )
            return ScoreResponse(
                success=True,
                result=result,
                score_time_seconds=round(time.time() - t, 2),
            )
        except Exception as exc:
            return ScoreResponse(success=False, error=str(exc))

    responses = list(await asyncio.gather(*[_score_one(r) for r in body.resumes]))
    responses.sort(
        key=lambda r: r.result.total_score if r.success and r.result else -1,
        reverse=True,
    )
    for rank, response in enumerate(responses, start=1):
        if response.success and response.result:
            response.result.rank = rank
    return responses


# ── JD Analysis ────────────────────────────────────────────────────────────


class JDTextInput(BaseModel):
    jd_text: str


@app.post("/jd/analyze", tags=["Job Description"])
def analyze_jd(payload: JDTextInput):
    """
    Extract structured requirement signals from a free-text Job Description.
    Returns required skills, preferred skills, experience level, qualifications,
    and role keywords — useful for previewing what the scorer will focus on.
    """
    requirements = parse_job_description(payload.jd_text)
    return {
        "success": True,
        "raw_text": payload.jd_text,
        "requirements": requirements,
    }


# ── Feedback loop ──────────────────────────────────────────────────────────


@app.post("/feedback", tags=["Feedback"])
def submit_feedback(payload: FeedbackRequest):
    """
    Submit recruiter feedback (employer score vs AI score) to calibrate future
    scoring for the same Job Description.
    The calibration offset is automatically applied to subsequent /score calls.
    """
    record = payload.model_dump()
    record["feedback_id"] = str(uuid4())
    if not record.get("resume_id") and record.get("resume_name"):
        record["resume_id"] = record["resume_name"]

    jd_id, calibration = add_feedback_record(record)
    return {
        "success": True,
        "feedback_id": record["feedback_id"],
        "jd_id": jd_id,
        "calibration": calibration,
    }


@app.get("/feedback/status/{jd_id}", tags=["Feedback"])
def feedback_status(jd_id: str):
    """
    Retrieve the current calibration state for a given Job Description ID.
    """
    return {"success": True, "calibration": get_calibration(jd_id)}
