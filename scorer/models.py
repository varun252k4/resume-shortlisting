from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


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
    contact: ContactInfo = Field(default_factory=ContactInfo)
    skills: list[str] = Field(default_factory=list)
    work_experience: list[WorkExperience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    raw_text: Optional[str] = None


class ParseResponse(BaseModel):
    success: bool
    filename: str
    data: Optional[ParsedResume] = None
    error: Optional[str] = None
    parse_time_seconds: Optional[float] = None


# ── Scoring Models (Phase 2) ───────────────────────────────────────────────


class MatchFlag(str, Enum):
    STRONG = "Strong Match"
    MODERATE = "Moderate Match"
    NO_MATCH = "Does Not Meet Requirements"


class WeightageConfig(BaseModel):
    skills: float = Field(default=0.40, ge=0, le=1)
    experience: float = Field(default=0.30, ge=0, le=1)
    education: float = Field(default=0.20, ge=0, le=1)
    certifications: float = Field(default=0.10, ge=0, le=1)

    @model_validator(mode="after")
    def _weights_sum_to_one(self):
        total = self.skills + self.experience + self.education + self.certifications
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Weightage values must sum to 1.0 (got {total:.2f})")
        return self


class JDRequirements(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    required_experience_years: Optional[float] = None
    qualifications: list[str] = Field(default_factory=list)
    role_keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _dedupe(self):
        self.required_skills = list({s.strip() for s in self.required_skills if s and s.strip()})
        self.preferred_skills = list({s.strip() for s in self.preferred_skills if s and s.strip()})
        self.qualifications = list({s.strip() for s in self.qualifications if s and s.strip()})
        self.role_keywords = list({s.strip() for s in self.role_keywords if s and s.strip()})
        return self

    def to_text(self) -> str:
        parts = []
        if self.required_skills:
            parts.append("Required skills: " + ", ".join(self.required_skills))
        if self.preferred_skills:
            parts.append("Preferred skills: " + ", ".join(self.preferred_skills))
        if self.required_experience_years is not None:
            parts.append(f"Required experience: {self.required_experience_years}+ years")
        if self.qualifications:
            parts.append("Qualifications: " + ", ".join(self.qualifications))
        if self.role_keywords:
            parts.append("Role keywords: " + ", ".join(self.role_keywords))
        return "\n".join(parts)


class JDInput(BaseModel):
    jd_text: Optional[str] = None
    requirements: Optional[JDRequirements] = None

    def resolved_text(self) -> str:
        if self.jd_text and self.jd_text.strip():
            return self.jd_text.strip()
        if self.requirements:
            return self.requirements.to_text()
        return ""

    @model_validator(mode="after")
    def _ensure_input(self):
        if not self.jd_text and not self.requirements:
            raise ValueError("Either jd_text or requirements must be provided.")
        if self.jd_text and not self.jd_text.strip() and not self.requirements:
            raise ValueError("jd_text cannot be empty when requirements are not provided.")
        return self


class ScoreBreakdown(BaseModel):
    skills: float
    experience: float
    education: float
    certifications: float


class ScoreResult(BaseModel):
    candidate_name: Optional[str] = None
    jd_id: str
    resume_id: str
    raw_total_score: float
    total_score: float
    calibration_offset: float = 0.0
    feedback_applied: bool = False
    breakdown: ScoreBreakdown
    flag: MatchFlag
    summary: str
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    is_shortlisted: bool = False
    rank: Optional[int] = None


class ScoreRequest(BaseModel):
    resume: ParsedResume
    jd_text: Optional[str] = None
    requirements: Optional[JDRequirements] = None
    weightage: WeightageConfig = WeightageConfig()
    use_ai_summary: bool = True
    shortlist_threshold: float = Field(default=50.0, ge=0, le=100)

    @model_validator(mode="after")
    def _require_jd_or_requirements(self):
        if not self.jd_text and not self.requirements:
            raise ValueError("Either jd_text or requirements must be supplied.")
        return self


class BatchScoreRequest(BaseModel):
    resumes: list[ParsedResume]
    jd_text: Optional[str] = None
    requirements: Optional[JDRequirements] = None
    weightage: WeightageConfig = WeightageConfig()
    use_ai_summary: bool = True
    shortlist_threshold: float = Field(default=50.0, ge=0, le=100)

    @model_validator(mode="after")
    def _require_jd_or_requirements(self):
        if not self.jd_text and not self.requirements:
            raise ValueError("Either jd_text or requirements must be supplied.")
        return self


class ScoreResponse(BaseModel):
    success: bool
    result: Optional[ScoreResult] = None
    error: Optional[str] = None
    score_time_seconds: Optional[float] = None


class FeedbackRequest(BaseModel):
    jd_text: Optional[str] = None
    jd_id: Optional[str] = None
    resume_id: Optional[str] = None
    resume_name: Optional[str] = None
    ai_total_score: float = Field(ge=0, le=100)
    ai_flag: MatchFlag
    employer_total_score: float = Field(ge=0, le=100)
    employer_flag: MatchFlag
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _require_reference(self):
        if not self.jd_id and not (self.jd_text and self.jd_text.strip()):
            raise ValueError("Either jd_id or jd_text must be provided.")
        if not self.resume_id and not self.resume_name:
            raise ValueError("Either resume_id or resume_name must be provided.")
        return self


class FeedbackEvent(BaseModel):
    feedback_id: str
    jd_id: str
    resume_id: str
    resume_name: Optional[str] = None
    ai_total_score: float
    ai_flag: MatchFlag
    employer_total_score: float
    employer_flag: MatchFlag
    created_at: str
    notes: Optional[str] = None


class FeedbackSummary(BaseModel):
    jd_id: str
    feedback_count: int
    feedback_alignment_pct: float
    calibration_offset: float
    last_recalibrated_at: str
    stale: bool = False