"""
Scoring orchestrator.

Responsibilities:
- index JD and resume into Chroma
- compute weighted similarity score
- apply optional employer feedback calibration
- generate short candidate summary
"""
from litellm import acompletion
from typing import Optional

from feedback_store import get_calibration
from jd_parser import parse_job_description
from models import JDRequirements
from models import MatchFlag, ParsedResume, ScoreBreakdown, ScoreResult, WeightageConfig
from vector_store import index_jd, index_resume, score_resume_against_jd
from config import LLM_API_KEY, LLM_MODEL


def _determine_flag(score: float) -> MatchFlag:
    if score >= 75:
        return MatchFlag.STRONG
    elif score >= 50:
        return MatchFlag.MODERATE
    return MatchFlag.NO_MATCH


def _build_summary_text(
    name: str,
    flag: MatchFlag,
    matched: list[str],
    missing: list[str],
    score: float,
) -> str:
    parts = [
        f"{name} scored {score:.1f}/100 and is currently flagged as {flag.value}.",
    ]
    if matched:
        parts.append("Strong matches include: " + ", ".join(matched[:5]) + ".")
    if missing:
        parts.append("Potential gaps: " + ", ".join(missing[:5]) + ".")
    if not matched and not missing:
        parts.append("Limited direct overlap was found with this job's requirements.")
    if len(parts) < 3:
        parts.append(
            "Score blends required skills, experience signals, education fit, and certification coverage."
        )
    return " ".join(parts)


def _merge_requirements(
    explicit: Optional[JDRequirements],
    extracted: Optional[JDRequirements],
) -> Optional[JDRequirements]:
    if explicit is None:
        return extracted
    if extracted is None:
        return explicit
        
    explicit_years = explicit.required_experience_years
    parsed_years = extracted.required_experience_years
    merged_years = explicit_years if explicit_years is not None else parsed_years
    
    return JDRequirements(
        required_skills=[*explicit.required_skills, *extracted.required_skills],
        preferred_skills=[*explicit.preferred_skills, *extracted.preferred_skills],
        required_experience_years=merged_years,
        qualifications=[*explicit.qualifications, *extracted.qualifications],
        role_keywords=[*explicit.role_keywords, *extracted.role_keywords],
    )


async def _build_summary(
    name: str,
    flag: MatchFlag,
    matched: list[str],
    missing: list[str],
    requirements: JDRequirements,
    score: float,
    use_ai: bool,
) -> str:
    if not use_ai:
        return _build_summary_text(name, flag, matched, missing, score)

    prompt = f"""
Write a concise 3-5 line hiring summary for a resume screening assistant.
Candidate: {name}
Flag: {flag.value}
Score: {score:.1f}
JD requirements: {requirements.to_text()}

Matched areas: {', '.join(matched[:6]) if matched else 'None'}
Missing areas: {', '.join(missing[:6]) if missing else 'None'}

Return plain text, no markdown or bullet symbols.
"""
    try:
        kwargs = {
            "model": LLM_MODEL,
            "max_tokens": 220,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        }
        if LLM_API_KEY:
            kwargs["api_key"] = LLM_API_KEY
        response = await acompletion(**kwargs)
        return response.choices[0].message.content.strip()
    except Exception:
        return _build_summary_text(name, flag, matched, missing, score)


async def _apply_calibration(jd_id: str, raw_score: float) -> tuple[float, dict]:
    calibration = await get_calibration(jd_id)
    offset = float(calibration.get("calibration_offset", 0.0))
    final_score = max(0.0, min(100.0, raw_score + offset))
    return final_score, calibration


async def score_candidate(
    resume: ParsedResume,
    jd_text: Optional[str],
    weightage: WeightageConfig,
    requirements: Optional[JDRequirements] = None,
    use_ai_summary: bool = True,
    shortlist_threshold: float = 50.0,
) -> ScoreResult:
    """
    Full scoring pipeline:
      1. Parse or validate JD input
      2. Index JD and resume fields
      3. Query similarity and compute weighted score
      4. Apply employer feedback calibration if available
      5. Generate candidate summary and return shortlist status
    """
    resolved_jd_text = (jd_text or "").strip()
    extracted_requirements = parse_job_description(resolved_jd_text)
    merged_requirements = _merge_requirements(requirements, extracted_requirements)
    if merged_requirements is None:
        merged_requirements = extracted_requirements

    scoring_text = resolved_jd_text or merged_requirements.to_text() or "Role requirements"

    jd_id = await index_jd(scoring_text, requirements=merged_requirements)

    # 3. Index resume fields into vectors
    resume_id = await index_resume(resume)

    # 4. Vector similarity scoring
    weight_dict = {
        "skills":           weightage.skills,
        "experience":       weightage.experience,
        "education":        weightage.education,
        "certifications":   weightage.certifications,
    }
    result = await score_resume_against_jd(jd_id, resume_id, weight_dict)

    # 5. Apply employer calibration
    calibrated_score, calibration = await _apply_calibration(jd_id, result["total_score"])

    # 6. Build summary
    matched = [p["resume_text"] for p in result["matched_pairs"] if p["category"] == "skill"]
    missing = result["missing"]
    flag = _determine_flag(calibrated_score)
    summary = await _build_summary(
        resume.name or "Candidate",
        flag,
        matched,
        missing,
        merged_requirements,
        calibrated_score,
        use_ai=use_ai_summary,
    )
    
    return ScoreResult(
        candidate_name=resume.name,
        jd_id=jd_id,
        resume_id=resume_id,
        raw_total_score=result["total_score"],
        total_score=calibrated_score,
        calibration_offset=float(calibration.get("calibration_offset", 0.0)),
        feedback_applied=calibration.get("feedback_count", 0) > 0,
        breakdown=ScoreBreakdown(**result["breakdown"]),
        flag=flag,
        summary=summary,
        matched_skills=matched,
        missing_skills=missing,
        is_shortlisted=calibrated_score >= shortlist_threshold,
    )