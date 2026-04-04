from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ── Resume Models (Phase 1) ────────────────────────────────────────────────

class ContactInfo(BaseModel):
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None


class WorkExperience(BaseModel):
    company: str
    role: str
    duration: Optional[str] = None
    description: Optional[str] = None


class Education(BaseModel):
    institution: str
    degree: str
    year: Optional[str | int] = None


class ParsedResume(BaseModel):
    name: Optional[str] = None
    contact: ContactInfo = ContactInfo()
    skills: list[str] = []
    work_experience: list[WorkExperience] = []
    education: list[Education] = []
    certifications: list[str] = []
    raw_text: Optional[str] = None


class ParseResponse(BaseModel):
    success: bool
    filename: str
    data: Optional[ParsedResume] = None
    error: Optional[str] = None
    parse_time_seconds: Optional[float] = None


# ── Scoring Models (Phase 2) ───────────────────────────────────────────────

class MatchFlag(str, Enum):
    STRONG      = "Strong Match"
    MODERATE    = "Moderate Match"
    NO_MATCH    = "Does Not Meet Requirements"


class WeightageConfig(BaseModel):
    skills: float          = Field(default=0.40, ge=0, le=1)
    experience: float      = Field(default=0.30, ge=0, le=1)
    education: float       = Field(default=0.20, ge=0, le=1)
    certifications: float  = Field(default=0.10, ge=0, le=1)

    def model_post_init(self, __context):
        total = self.skills + self.experience + self.education + self.certifications
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Weightage values must sum to 1.0 (got {total:.2f})")


class ScoreBreakdown(BaseModel):
    skills: float
    experience: float
    education: float
    certifications: float


class ScoreResult(BaseModel):
    candidate_name: Optional[str] = None
    total_score: float
    breakdown: ScoreBreakdown
    flag: MatchFlag
    summary: str
    matched_skills: list[str] = []
    missing_skills: list[str] = []


class ScoreRequest(BaseModel):
    resume: ParsedResume
    jd_text: str                        # raw JD text — no pre-parsing needed
    weightage: WeightageConfig = WeightageConfig()


class BatchScoreRequest(BaseModel):
    resumes: list[ParsedResume]
    jd_text: str                        # same raw JD for all candidates
    weightage: WeightageConfig = WeightageConfig()


class ScoreResponse(BaseModel):
    success: bool
    result: Optional[ScoreResult] = None
    error: Optional[str] = None
    score_time_seconds: Optional[float] = None