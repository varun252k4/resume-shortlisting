import time
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from uuid import uuid4

from scorer.feedback_store import add_feedback_record, get_calibration
from scorer.models import (
    ParsedResume, ParseResponse, ContactInfo, WorkExperience, Education,
    ScoreRequest, ScoreResponse, BatchScoreRequest, FeedbackRequest,
)
from resume_parser import extract_raw_text, clean_text
from resume_parser.extractor import extract_fields
from scorer.scorer import score_candidate
from scorer.jd_parser import parse_job_description

app = FastAPI(
    title="AI Resume Screening API",
    description="Phase 1: Resume parsing. Phase 2: Vector-based JD matching.",
    version="3.1.0",
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

@app.get("/health")
def health():
    return {"status": "ok"}


# ── Phase 1: Resume Parsing ────────────────────────────────────────────────

async def _parse_file(filename: str, file_bytes: bytes) -> ParseResponse:
    start = time.time()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return ParseResponse(success=False, filename=filename,
                             error=f"Unsupported file type '.{ext}'.")
    try:
        raw_text = extract_raw_text(filename, file_bytes)
        raw_text = clean_text(raw_text)
        if not raw_text.strip():
            raise ValueError("No readable text found in document.")
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
            success=True, filename=filename, data=parsed,
            parse_time_seconds=round(time.time() - start, 2),
        )
    except Exception as e:
        return ParseResponse(success=False, filename=filename, error=str(e))


@app.post("/parse", response_model=ParseResponse)
async def parse_resume(file: UploadFile = File(...)):
    """Upload a single resume (PDF/DOCX/TXT) → structured JSON."""
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_FILE_SIZE_MB}MB.")
    return await _parse_file(file.filename, file_bytes)


@app.post("/parse/batch", response_model=list[ParseResponse])
async def parse_batch(files: list[UploadFile] = File(...)):
    """Upload up to 500 resumes and parse them concurrently."""
    if len(files) > 500:
        raise HTTPException(status_code=400, detail="Max 500 resumes per batch.")
    tasks = [(f.filename, await f.read()) for f in files]
    return list(await asyncio.gather(*[_parse_file(fn, fb) for fn, fb in tasks]))


# ── Phase 2: Scoring ───────────────────────────────────────────────────────

@app.post("/score", response_model=ScoreResponse)
async def score_single(body: ScoreRequest):
    """
    Score one resume against a raw JD text.
    JD is embedded into vectors automatically — no pre-parsing step needed.
    Same JD text used multiple times → ChromaDB caches it automatically.
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
    except Exception as e:
        return ScoreResponse(success=False, error=str(e))


@app.post("/score/batch", response_model=list[ScoreResponse])
async def score_batch(body: BatchScoreRequest):
    """
    Score multiple resumes against the same JD concurrently.
    JD is embedded once and reused across all candidates.
    Results sorted by score descending.
    """
    if len(body.resumes) > 500:
        raise HTTPException(status_code=400, detail="Max 500 resumes per batch.")

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
            return ScoreResponse(success=True, result=result,
                                 score_time_seconds=round(time.time() - t, 2))
        except Exception as e:
            return ScoreResponse(success=False, error=str(e))

    results = list(await asyncio.gather(*[_score_one(r) for r in body.resumes]))
    results.sort(
        key=lambda r: r.result.total_score if r.success and r.result else -1,
        reverse=True,
    )
    for idx, response in enumerate(results, start=1):
        if response.success and response.result:
            response.result.rank = idx
    return results


# ── JD tools ────────────────────────────────────────────────────────────────


class JDTextInput(BaseModel):
    jd_text: str


@app.post("/jd/analyze")
def analyze_jd(payload: JDTextInput):
    """
    Parse structured job-requirement signals from free text.
    """
    requirements = parse_job_description(payload.jd_text)
    return {
        "success": True,
        "raw_text": payload.jd_text,
        "requirements": requirements,
    }


# ── Feedback loop ──────────────────────────────────────────────────────────


@app.post("/feedback")
def submit_feedback(payload: FeedbackRequest):
    """
    Store recruiter feedback and apply calibration signals for future score runs.
    """
    payload_dict = payload.model_dump()
    payload_dict["feedback_id"] = str(uuid4())
    if not payload_dict.get("resume_id") and payload_dict.get("resume_name"):
        payload_dict["resume_id"] = payload_dict["resume_name"]

    jd_id, calibration = add_feedback_record(payload_dict)

    return {
        "success": True,
        "feedback_id": payload_dict["feedback_id"],
        "jd_id": jd_id,
        "calibration": calibration,
    }


@app.get("/feedback/status/{jd_id}")
def feedback_status(jd_id: str):
    return {"success": True, "calibration": get_calibration(jd_id)}