"""
Scorer — orchestrates vector indexing + similarity + deterministic summary.
JD parser LLM call is gone. Everything goes through vectors.
No LLM calls are used during the scoring phase.
"""
from models import ParsedResume, WeightageConfig, ScoreBreakdown, ScoreResult, MatchFlag
from vector_store import index_jd, index_resume, score_resume_against_jd


def _determine_flag(score: float) -> MatchFlag:
    if score >= 75:
        return MatchFlag.STRONG
    elif score >= 50:
        return MatchFlag.MODERATE
    return MatchFlag.NO_MATCH


def _build_summary(name: str, flag: MatchFlag, matched: list[str], missing: list[str]) -> str:
    parts = []
    if flag == MatchFlag.STRONG:
        parts.append(f"{name} is a strong match for this role based on your JD.")
    elif flag == MatchFlag.MODERATE:
        parts.append(f"{name} is a moderate match for this role.")
    else:
        parts.append(f"{name} does not meet the core requirements for this role.")
        
    if matched:
        parts.append(f"Top matched skills include: {', '.join(matched[:5])}.")
    if missing:
        parts.append(f"Key missing skills: {', '.join(missing[:5])}.")
    
    return " ".join(parts)


async def score_candidate(
    resume: ParsedResume,
    jd_text: str,                 # raw JD text — no parsing needed
    weightage: WeightageConfig,
) -> ScoreResult:
    """
    Full scoring pipeline:
      1. Embed JD raw text → ChromaDB (once per unique JD)
      2. Embed resume fields → ChromaDB
      3. Query resume vectors against JD vectors → similarity scores
      4. LLM generates summary (1 call per candidate)
    """
    # 1. Index JD (raw text, no LLM)
    jd_id = await index_jd(jd_text)

    # 2. Index resume fields into vectors
    resume_id = await index_resume(resume)

    # 3. Vector similarity scoring
    weight_dict = {
        "skills":           weightage.skills,
        "experience":       weightage.experience,
        "education":        weightage.education,
        "certifications":   weightage.certifications,
    }
    result = await score_resume_against_jd(jd_id, resume_id, weight_dict)

    # 4. Deterministic summary
    matched = [p["resume_text"] for p in result["matched_pairs"] if p["category"] == "skill"]
    missing = result["missing"]
    flag = _determine_flag(result["total_score"])
    
    summary = _build_summary(resume.name or "Candidate", flag, matched, missing)

    return ScoreResult(
        candidate_name=resume.name,
        total_score=result["total_score"],
        breakdown=ScoreBreakdown(**result["breakdown"]),
        flag=flag,
        summary=summary,
        matched_skills=matched,
        missing_skills=missing,
    )