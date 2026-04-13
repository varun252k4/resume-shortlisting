import asyncio
import os
import sys

# Add both resume_parser/ and scorer/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "resume_parser"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scorer"))

from scorer.feedback_store import add_feedback_record, get_calibration
from resume_parser import extract_raw_text, clean_text
from resume_parser.extractor import extract_fields
from scorer.jd_parser import parse_job_description
from scorer.scorer import score_candidate
from scorer.models import (
    ContactInfo,
    Education,
    FeedbackRequest,
    JDRequirements,
    MatchFlag,
    ParsedResume,
    WeightageConfig,
    WorkExperience,
)


# ── Sample Job Description ─────────────────────────────────────────────────
SAMPLE_JD = """
Job Title: Machine Learning Engineer

We are looking for a Machine Learning Engineer to join our AI team.

Requirements:
- 2+ years of experience in machine learning or data science
- Proficiency in Python and TensorFlow or PyTorch
- Experience with deep learning, CNNs, and NLP
- Familiarity with cloud platforms (AWS, GCP, or Azure)
- Strong understanding of data preprocessing and model evaluation

Nice to have:
- Experience with MLOps tools (MLflow, Kubeflow)
- Knowledge of REST API development with FastAPI or Flask
- Certifications: AWS Certified Machine Learning Specialty, TensorFlow Developer Certificate

Education: Bachelor's degree in Computer Science, AI, or related field
"""


async def main():
    # ── Step 1: Parse Resume ───────────────────────────────────────────────
    resume_path = "Varun_Vangar_Resume.pdf"
    print(f"{'='*55}")
    print(f"  STEP 1: Parsing resume — {resume_path}")
    print(f"{'='*55}")

    if os.path.exists(resume_path):
        with open(resume_path, "rb") as f:
            file_bytes = f.read()

        raw_text = extract_raw_text(resume_path, file_bytes)
        raw_text = clean_text(raw_text)
        print(f"Extracted {len(raw_text)} characters of text from PDF")

        print("Calling LLM for resume extraction...")
        extracted = await extract_fields(raw_text)
        resume = ParsedResume(
            name=extracted.get("name"),
            contact=ContactInfo(**extracted.get("contact", {})),
            skills=extracted.get("skills", []),
            work_experience=[WorkExperience(**e) for e in extracted.get("work_experience", [])],
            education=[Education(**e) for e in extracted.get("education", [])],
            certifications=extracted.get("certifications", []),
            raw_text=raw_text,
        )
    else:
        print("Resume file not found. Using fallback parsed resume sample for scoring demo.")
        resume = ParsedResume(
            name="Demo Candidate",
            contact=ContactInfo(),
            skills=["Python", "TensorFlow", "PyTorch", "NLP", "SQL", "AWS", "FastAPI"],
            work_experience=[
                WorkExperience(
                    role="Machine Learning Engineer",
                    company="Demo Labs",
                    duration="Jan 2021 - Present",
                    description="Built ML models for NLP and recommendation systems.",
                )
            ],
            education=[
                Education(
                    degree="B.Tech Computer Science",
                    institution="Example Institute",
                    start_year=2020,
                )
            ],
            certifications=["AWS Certified Machine Learning Specialty", "TensorFlow Developer Certificate"],
            raw_text="Machine learning engineer with TensorFlow and PyTorch experience.",
        )

    print(f"- Candidate: {resume.name}")
    print(f"- Skills ({len(resume.skills)}): {', '.join(resume.skills[:8])}{'...' if len(resume.skills) > 8 else ''}")
    print(f"- Experience roles: {', '.join(e.role for e in resume.work_experience)}")
    print(f"- Education: {', '.join(e.degree for e in resume.education)}")
    print(f"- Certifications: {', '.join(resume.certifications) or 'None'}")

    # ── Step 1b: JD extraction from free-text ─────────────────────────────
    print(f"\n{'='*55}")
    print(f"  STEP 1b: Heuristic JD requirements extraction")
    print(f"{'='*55}")
    extracted_requirements = parse_job_description(SAMPLE_JD)
    print(f"- Required skills: {', '.join(extracted_requirements.required_skills) or 'None'}")
    print(f"- Preferred skills: {', '.join(extracted_requirements.preferred_skills) or 'None'}")
    print(f"- Required experience: {extracted_requirements.required_experience_years or 'Not specified'}")
    print(f"- Qualifications: {', '.join(extracted_requirements.qualifications) or 'None'}")

    # ── Step 2: Vector scoring (JD embedded automatically) ────────────────
    print(f"\n{'='*55}")
    print(f"  STEP 2: Scoring via vector similarity")
    print(f"{'='*55}")
    print("Embedding JD + resume into ChromaDB with custom requirement structuring...")
    print("(First run downloads embedding model ~130MB — please wait)\n")

    weightage = WeightageConfig(skills=0.60, experience=0.20, education=0.15, certifications=0.05)
    explicit_requirements = JDRequirements(
        required_skills=extracted_requirements.required_skills[:3],
        preferred_skills=extracted_requirements.preferred_skills[:2],
        required_experience_years=3.0,
        qualifications=extracted_requirements.qualifications,
        role_keywords=["Machine Learning Engineer", "AI", "NLP"],
    )

    result = await score_candidate(
        resume,
        SAMPLE_JD,
        weightage,
        requirements=explicit_requirements,
        use_ai_summary=False,
        shortlist_threshold=55.0,
    )

    print(f"\n  Candidate : {result.candidate_name}")
    print(f"  Flag      : {result.flag.value}")
    print(f"  Score raw : {result.raw_total_score:.2f}/100")
    print(f"  Score adj : {result.total_score:.2f}/100")
    print(f"  Calib     : {result.calibration_offset:+.2f}")
    print(f"  Feedback  : {result.feedback_applied}")
    print(f"  Shortlist : {result.is_shortlisted}")
    print(f"\n  Breakdown:")
    print(f"    Skills          : {result.breakdown.skills}")
    print(f"    Experience      : {result.breakdown.experience}")
    print(f"    Education       : {result.breakdown.education}")
    print(f"    Certifications  : {result.breakdown.certifications}")
    print(f"\n  Matched skills  : {', '.join(result.matched_skills) or 'None'}")
    print(f"  Missing skills  : {', '.join(result.missing_skills) or 'None'}")
    print(f"\n  Summary:\n  {result.summary}")

    # ── Step 3: Employer feedback + recalibration demo ─────────────────────
    print(f"\n{'='*55}")
    print(f"  STEP 3: Feedback loop calibration demo")
    print(f"{'='*55}")
    print(f"Current calibration before feedback: {get_calibration(result.jd_id)}")

    employer_score = min(100.0, result.total_score + 12.0)
    employer_flag = result.flag
    if result.flag != MatchFlag.STRONG:
        employer_flag = MatchFlag.STRONG

    fb = FeedbackRequest(
        jd_id=result.jd_id,
        resume_id=result.resume_id,
        resume_name=resume.name,
        ai_total_score=result.total_score,
        ai_flag=result.flag,
        employer_total_score=employer_score,
        employer_flag=employer_flag,
        notes="Evaluator confirmed stronger fit than AI suggested.",
    )
    feedback_id, calibration = add_feedback_record(fb.model_dump())
    print(f"Feedback saved: {feedback_id}")
    print(f"Updated calibration: {calibration}")

    recalibrated = await score_candidate(
        resume,
        SAMPLE_JD,
        weightage,
        requirements=explicit_requirements,
        use_ai_summary=False,
        shortlist_threshold=55.0,
    )
    print(f"\n  After feedback + recalibration:")
    print(f"  Candidate : {recalibrated.candidate_name}")
    print(f"  Flag      : {recalibrated.flag.value}")
    print(f"  Score raw : {recalibrated.raw_total_score:.2f}/100")
    print(f"  Score adj : {recalibrated.total_score:.2f}/100")
    print(f"  Calib     : {recalibrated.calibration_offset:+.2f}")
    print(f"  Feedback  : {recalibrated.feedback_applied}")
    print(f"  Shortlist : {recalibrated.is_shortlisted}")

    # ── Step 4: Structured JD only scoring path ─────────────────────────────
    print(f"\n{'='*55}")
    print(f"  STEP 4: Structured requirements-only scoring")
    print(f"{'='*55}")
    structured_only_result = await score_candidate(
        resume,
        jd_text=None,
        weightage=weightage,
        requirements=JDRequirements(
            required_skills=["Python", "Machine Learning"],
            required_experience_years=2,
            qualifications=["B.Tech"],
        ),
        use_ai_summary=False,
    )
    print(f"  Structured-only flag: {structured_only_result.flag.value}")
    print(f"  Structured-only score: {structured_only_result.total_score:.2f}/100")


asyncio.run(main())
