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
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import Optional, Union

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

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

JWT_SECRET = os.getenv("JWT_SECRET", "replace-this-please")
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "1440"))
AUTH_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
AUTH_DATA_FILE = os.path.join(AUTH_DATA_DIR, "app_store.json")
AUTH_STORE_LOCK = threading.Lock()
auth_scheme = HTTPBearer(auto_error=False)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_auth_store() -> dict:
    return {"users": [], "resumes": [], "jobs": [], "rankings": {}}


def _load_auth_store() -> dict:
    if not os.path.exists(AUTH_DATA_DIR):
        os.makedirs(AUTH_DATA_DIR, exist_ok=True)

    if not os.path.exists(AUTH_DATA_FILE):
        _save_auth_store(_default_auth_store())

    with open(AUTH_DATA_FILE, "r", encoding="utf-8") as fp:
        try:
            return json.load(fp)
        except json.JSONDecodeError:
            return _default_auth_store()


def _save_auth_store(state: dict) -> None:
    with AUTH_STORE_LOCK:
        if not os.path.exists(AUTH_DATA_DIR):
            os.makedirs(AUTH_DATA_DIR, exist_ok=True)
        with open(AUTH_DATA_FILE, "w", encoding="utf-8") as fp:
            json.dump(state, fp, indent=2)


def _normalize_role(role: str) -> str:
    normalized = (role or "").strip().lower()
    if normalized in {"employee", "emp", "candidate"}:
        return "candidate"
    if normalized in {"employer", "recruiter"}:
        return "employer"
    if normalized == "admin":
        return "admin"
    raise ValueError("Invalid role. Use 'employee' or 'employer'.")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"pbkdf2${salt}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    if not encoded or not encoded.startswith("pbkdf2$"):
        return False
    try:
        _, salt, hash_hex = encoded.split("$", 2)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return hmac.compare_digest(hash_hex, digest.hex())


def _b64url(data: Union[str, bytes]) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - (len(value) % 4)) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _sign_message(message: str) -> str:
    sig = hmac.new(JWT_SECRET.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64url(sig)


def _create_jwt(payload: dict) -> str:
    now = int(time.time())
    token_payload = {
        "iss": "resume-shortlisting",
        "iat": now,
        "exp": now + (JWT_EXPIRES_MINUTES * 60),
        **payload,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _b64url(json.dumps(header, separators=(",", ":")))
    encoded_payload = _b64url(json.dumps(token_payload, separators=(",", ":")))
    signature = _sign_message(f"{encoded_header}.{encoded_payload}")
    return f"{encoded_header}.{encoded_payload}.{signature}"


def _decode_jwt(token: str) -> dict:
    try:
        encoded_header, encoded_payload, signature = token.split(".")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token format.") from exc

    expected = _sign_message(f"{encoded_header}.{encoded_payload}")
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid token signature.")

    payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired.")
    return payload


def _current_user_payload(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication credentials are missing.")
    return _decode_jwt(credentials.credentials)


def _require_role(*roles: str):
    allowed = set(roles)

    def checker(payload: dict = Depends(_current_user_payload)) -> dict:
        role = payload.get("role")
        if role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions for this action.")
        return payload

    return checker


def _sanitize_user(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
    }


class SignupInput(BaseModel):
    name: str
    email: str
    password: str
    role: str


class SigninInput(BaseModel):
    email: str
    password: str


class JobCreateInput(BaseModel):
    title: str
    jd_text: str


class RankRequest(BaseModel):
    resume_ids: list[str] = Field(default_factory=list)
    requirements: Optional[JDRequirements] = None
    weightage: WeightageConfig = WeightageConfig()
    use_ai_summary: bool = True
    shortlist_threshold: float = Field(default=50.0, ge=0, le=100)


class AuthResponse(BaseModel):
    success: bool
    token: str
    user: dict


@app.middleware("http")
async def jwt_context_middleware(request: Request, call_next):
    request.state.jwt_user = None
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        try:
            request.state.jwt_user = _decode_jwt(auth.split(" ", 1)[1])
        except HTTPException:
            request.state.jwt_user = None
    return await call_next(request)


def _find_user(store: dict, user_id: str) -> Optional[dict]:
    for user in store["users"]:
        if user["id"] == user_id:
            return user
    return None


def _find_user_by_email(store: dict, email: str) -> Optional[dict]:
    lowered = email.lower()
    for user in store["users"]:
        if user["email"] == lowered:
            return user
    return None


def _find_job(store: dict, job_id: str) -> Optional[dict]:
    for job in store["jobs"]:
        if job["id"] == job_id:
            return job
    return None


def _make_token_payload(user: dict) -> tuple[str, dict]:
    token = _create_jwt(
        {
            "sub": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
        },
    )
    return token, _sanitize_user(user)


@app.post("/auth/signup", response_model=AuthResponse, tags=["Auth"])
async def signup(payload: SignupInput):
    role = _normalize_role(payload.role)
    email = payload.email.strip().lower()

    store = _load_auth_store()
    if _find_user_by_email(store, email):
        raise HTTPException(status_code=409, detail="Email already registered.")

    user = {
        "id": str(uuid4()),
        "name": payload.name.strip(),
        "email": email,
        "password": _hash_password(payload.password),
        "role": role,
        "created_at": _iso_now(),
    }
    store["users"].append(user)
    _save_auth_store(store)

    token, public_user = _make_token_payload(user)
    return AuthResponse(success=True, token=token, user=public_user)


@app.post("/auth/login", response_model=AuthResponse, tags=["Auth"])
async def login(payload: SigninInput):
    store = _load_auth_store()
    user = _find_user_by_email(store, payload.email.strip().lower())
    if not user or not _verify_password(payload.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    token, public_user = _make_token_payload(user)
    return AuthResponse(success=True, token=token, user=public_user)


@app.post("/auth/signin", response_model=AuthResponse, tags=["Auth"])
async def signin(payload: SigninInput):
    return await login(payload)


@app.get("/auth/me", tags=["Auth"])
async def me(payload: dict = Depends(_current_user_payload)):
    store = _load_auth_store()
    user = _find_user(store, payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="Invalid user.")
    return {"success": True, "user": _sanitize_user(user)}


@app.get("/candidate/resumes", tags=["Resumes"])
async def list_candidate_resumes(user: dict = Depends(_current_user_payload)):
    store = _load_auth_store()
    all_resumes = store["resumes"]
    if user["role"] == "candidate":
        all_resumes = [item for item in all_resumes if item["user_id"] == user["sub"]]
    return {"success": True, "resumes": all_resumes}


@app.post("/candidate/resumes", tags=["Resumes"])
async def upload_candidate_resumes(
    files: list[UploadFile] = File(...),
    user: dict = Depends(_require_role("candidate")),
):
    if not files:
        raise HTTPException(status_code=400, detail="At least one resume file is required.")

    added = []
    failed = []
    store = _load_auth_store()

    for file in files:
        parsed = await _parse_file(file.filename, await file.read())
        if not parsed.success or not parsed.data:
            failed.append(file.filename)
            continue

        resume_id = str(uuid4())
        resume_record = {
            "id": resume_id,
            "user_id": user["sub"],
            "candidate_name": parsed.data.name or file.filename,
            "file_name": file.filename,
            "parsed": parsed.data.model_dump(),
            "uploaded_at": _iso_now(),
        }
        store["resumes"].append(resume_record)
        added.append(resume_record)

    _save_auth_store(store)
    return {"success": True, "added": added, "failed": failed}


@app.post("/employer/jobs", tags=["Recruitment"])
async def create_job(payload: JobCreateInput, user: dict = Depends(_require_role("employer"))):
    jd_text = (payload.jd_text or "").strip()
    if not jd_text:
        raise HTTPException(status_code=400, detail="JD text is required.")

    store = _load_auth_store()
    title = (payload.title or "Job Role").strip() or "Job Role"

    job = {
        "id": str(uuid4()),
        "employer_id": user["sub"],
        "title": title,
        "jd_text": jd_text,
        "created_at": _iso_now(),
    }
    store["jobs"].append(job)
    _save_auth_store(store)
    return {"success": True, "job": job}


@app.get("/employer/jobs", tags=["Recruitment"])
async def list_jobs(user: dict = Depends(_require_role("employer"))):
    store = _load_auth_store()
    jobs = [job for job in store["jobs"] if job["employer_id"] == user["sub"]]
    return {"success": True, "jobs": jobs}


@app.post("/employer/jobs/{job_id}/rank", tags=["Recruitment"])
async def rank_job(job_id: str, payload: RankRequest, user: dict = Depends(_require_role("employer"))):
    store = _load_auth_store()
    job = _find_job(store, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    if job["employer_id"] != user["sub"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="You can only rank resumes for your own jobs.")

    available_resumes = store["resumes"]
    requested_ids = set(payload.resume_ids)
    if requested_ids:
        available_resumes = [resume for resume in available_resumes if resume["id"] in requested_ids]

    if not available_resumes:
        return {
            "success": False,
            "job_id": job_id,
            "results": [],
            "errors": ["No resumes available for ranking."],
        }

    async def _score_one(record: dict):
        parsed = ParsedResume(**record["parsed"])
        result = await score_candidate(
            parsed,
            job["jd_text"],
            payload.weightage,
            requirements=payload.requirements,
            use_ai_summary=payload.use_ai_summary,
            shortlist_threshold=payload.shortlist_threshold,
        )
        output = result.model_dump()
        output["resume_id"] = record["id"]
        output["resume_name"] = record.get("file_name")
        return output

    scored = await asyncio.gather(*[_score_one(r) for r in available_resumes], return_exceptions=True)
    output_scores = []
    errors = []

    for result in scored:
        if isinstance(result, Exception):
            errors.append(str(result))
            continue
        output_scores.append(result)

    output_scores.sort(key=lambda r: r.get("total_score", 0), reverse=True)
    for idx, item in enumerate(output_scores, start=1):
        item["rank"] = idx

    store["rankings"][job_id] = {
        "job_id": job_id,
        "generated_by": user["sub"],
        "results": output_scores,
        "errors": errors,
        "generated_at": _iso_now(),
    }
    _save_auth_store(store)

    return {"success": True, "job_id": job_id, "results": output_scores, "errors": errors}


@app.get("/employer/jobs/{job_id}/rankings", tags=["Recruitment"])
async def get_job_rankings(job_id: str, user: dict = Depends(_require_role("employer"))):
    store = _load_auth_store()
    job = _find_job(store, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    ranking = store["rankings"].get(job_id)
    if not ranking:
        return {"success": False, "job_id": job_id, "results": []}

    if ranking.get("generated_by") and ranking["generated_by"] != user["sub"] and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="You can only view rankings for your own jobs.")

    return {"success": True, "job_id": job_id, "results": ranking["results"], "errors": ranking.get("errors", [])}


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
