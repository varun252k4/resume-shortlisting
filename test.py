import asyncio
import sys
import os

# Add both parser/ and scorer/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "parser"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scorer"))

from parser import extract_raw_text, clean_text
from extractor import extract_fields
from scorer import score_candidate
from models import (
    ParsedResume, ContactInfo, WorkExperience, Education,
    WeightageConfig,
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

    with open(resume_path, "rb") as f:
        file_bytes = f.read()

    raw_text = extract_raw_text(resume_path, file_bytes)
    raw_text = clean_text(raw_text)
    print(f"Extracted {len(raw_text)} characters of text\n")

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
    print(f"- Candidate: {resume.name}")
    print(f"- Skills ({len(resume.skills)}): {', '.join(resume.skills[:8])}{'...' if len(resume.skills) > 8 else ''}")
    print(f"- Experience roles: {', '.join(e.role for e in resume.work_experience)}")
    print(f"- Education: {', '.join(e.degree for e in resume.education)}")
    print(f"- Certifications: {', '.join(resume.certifications) or 'None'}")

    # ── Step 2: Vector scoring (JD embedded automatically) ────────────────
    print(f"\n{'='*55}")
    print(f"  STEP 2: Scoring via vector similarity")
    print(f"{'='*55}")
    print("Embedding JD + resume into ChromaDB...")
    print("(First run downloads embedding model ~130MB — please wait)\n")

    weightage = WeightageConfig()  # skills=0.4, exp=0.3, edu=0.2, cert=0.1
    result = await score_candidate(resume, SAMPLE_JD, weightage)

    print(f"\n  Candidate : {result.candidate_name}")
    print(f"  Flag      : {result.flag.value}")
    print(f"  Total     : {result.total_score}/100")
    print(f"\n  Breakdown:")
    print(f"    Skills          : {result.breakdown.skills}")
    print(f"    Experience      : {result.breakdown.experience}")
    print(f"    Education       : {result.breakdown.education}")
    print(f"    Certifications  : {result.breakdown.certifications}")
    print(f"\n  Matched skills  : {', '.join(result.matched_skills) or 'None'}")
    print(f"  Missing skills  : {', '.join(result.missing_skills) or 'None'}")
    print(f"\n  Summary:\n  {result.summary}")


asyncio.run(main())
