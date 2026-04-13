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
    JDRequirements,
    ParsedResume,
    ParseResponse,
    ScoreRequest,
    ScoreResponse,
    ShortlistBatchResponse,
    ShortlistCandidate,
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


# ── End-to-end Batch Shortlisting ─────────────────────────────────────────


@app.post("/shortlist/batch", response_model=ShortlistBatchResponse, tags=["Shortlisting"])
async def shortlist_batch(
    files: list[UploadFile] = File(...),
    jd_text: str = File(...),
    weightage_skills: float = File(default=0.40),
    weightage_experience: float = File(default=0.30),
    weightage_education: float = File(default=0.20),
    weightage_certifications: float = File(default=0.10),
    shortlist_threshold: float = File(default=50.0),
    use_ai_summary: bool = File(default=False),
):
    """
    **Single-call batch shortlisting.**

    Upload up to 500 resume files together with a Job Description and get back
    ranked, scored, and flagged candidates in one operation.

    Steps performed internally:
    1. Parse every resume concurrently (PDF / DOCX / TXT).
    2. Score each parsed resume against the JD using vector similarity.
    3. Apply custom weightage, calibration, and shortlist threshold.
    4. Return results sorted by score descending with rank assigned.

    Form fields:
    - `files` — one or more resume files (multi-file upload)
    - `jd_text` — raw Job Description text
    - `weightage_*` — optional per-dimension weights (must sum to 1.0)
    - `shortlist_threshold` — minimum score to mark `is_shortlisted=True` (default 50)
    - `use_ai_summary` — generate LLM narrative summaries (default false for speed)
    """
    if len(files) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 resumes per batch.")
    if not jd_text or not jd_text.strip():
        raise HTTPException(status_code=400, detail="jd_text must not be empty.")

    try:
        weightage = WeightageConfig(
            skills=weightage_skills,
            experience=weightage_experience,
            education=weightage_education,
            certifications=weightage_certifications,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    payloads = [(f.filename, await f.read()) for f in files]

    async def _process_one(filename: str, file_bytes: bytes) -> ShortlistCandidate:
        t = time.time()
        parse_result = await _parse_file(filename, file_bytes)
        if not parse_result.success or parse_result.data is None:
            return ShortlistCandidate(
                filename=filename,
                parse_success=False,
                parse_error=parse_result.error,
                score_success=False,
                total_time_seconds=round(time.time() - t, 2),
            )
        try:
            score_result = await score_candidate(
                parse_result.data,
                jd_text,
                weightage,
                requirements=None,
                use_ai_summary=use_ai_summary,
                shortlist_threshold=shortlist_threshold,
            )
            return ShortlistCandidate(
                filename=filename,
                parse_success=True,
                score_success=True,
                parsed_resume=parse_result.data,
                result=score_result,
                total_time_seconds=round(time.time() - t, 2),
            )
        except Exception as exc:
            return ShortlistCandidate(
                filename=filename,
                parse_success=True,
                score_success=False,
                score_error=str(exc),
                parsed_resume=parse_result.data,
                total_time_seconds=round(time.time() - t, 2),
            )

    candidates = list(await asyncio.gather(*[_process_one(fn, fb) for fn, fb in payloads]))

    # Sort successfully scored candidates by score descending; failed ones go last
    candidates.sort(
        key=lambda c: c.result.total_score if c.score_success and c.result else -1,
        reverse=True,
    )
    for rank, candidate in enumerate(candidates, start=1):
        if candidate.score_success and candidate.result:
            candidate.result.rank = rank

    shortlisted_count = sum(
        1 for c in candidates
        if c.score_success and c.result and c.result.is_shortlisted
    )
    return ShortlistBatchResponse(
        total=len(candidates),
        shortlisted=shortlisted_count,
        candidates=candidates,
    )


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
