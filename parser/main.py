import time
import asyncio
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import ParsedResume, ParseResponse, ContactInfo, WorkExperience, Education
from parser import extract_raw_text, clean_text
from extractor import extract_fields

app = FastAPI(
    title="Resume Parser API",
    description="Extracts structured data from PDF, DOCX, and TXT resumes.",
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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/parse", response_model=ParseResponse)
async def parse_resume(file: UploadFile = File(...)):
    """
    Upload a resume (PDF, DOCX, or TXT) and receive structured extracted data.
    Target: < 5 seconds per document.
    """
    start = time.time()

    # Validate extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Allowed: PDF, DOCX, TXT.",
        )

    file_bytes = await file.read()

    # Validate size
    if len(file_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {MAX_FILE_SIZE_MB}MB limit.",
        )

    try:
        # Step 1: Extract raw text from document
        raw_text = extract_raw_text(file.filename, file_bytes)
        raw_text = clean_text(raw_text)

        if not raw_text.strip():
            raise ValueError("No readable text found in the document.")

        # Step 2: Claude extracts structured fields
        extracted = await extract_fields(raw_text)

        # Step 3: Map into Pydantic models
        parsed = ParsedResume(
            name=extracted.get("name"),
            contact=ContactInfo(**extracted.get("contact", {})),
            skills=extracted.get("skills", []),
            work_experience=[
                WorkExperience(**exp)
                for exp in extracted.get("work_experience", [])
            ],
            education=[
                Education(**edu)
                for edu in extracted.get("education", [])
            ],
            certifications=extracted.get("certifications", []),
            raw_text=raw_text,
        )

        return ParseResponse(
            success=True,
            filename=file.filename,
            data=parsed,
            parse_time_seconds=round(time.time() - start, 2),
        )

    except ValueError as e:
        return ParseResponse(success=False, filename=file.filename, error=str(e))
    except Exception as e:
        return ParseResponse(
            success=False,
            filename=file.filename,
            error=f"Parsing failed: {str(e)}",
        )


@app.post("/parse/batch", response_model=list[ParseResponse])
async def parse_batch(files: list[UploadFile] = File(...)):
    """
    Upload multiple resumes and parse them concurrently.
    Supports up to 500 files per batch.
    """
    if len(files) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 resumes per batch.")

    # Read all files first
    tasks = []
    for f in files:
        content = await f.read()
        tasks.append((f.filename, content))

    # Parse all concurrently
    async def parse_one(filename, file_bytes):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        start = time.time()
        try:
            raw_text = extract_raw_text(filename, file_bytes)
            raw_text = clean_text(raw_text)
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
        except Exception as e:
            return ParseResponse(success=False, filename=filename, error=str(e))

    results = await asyncio.gather(*[parse_one(fn, fb) for fn, fb in tasks])
    return list(results)
