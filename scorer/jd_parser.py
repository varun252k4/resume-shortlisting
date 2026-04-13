"""
Heuristic JD parsing helpers.

This keeps the scoring pipeline lightweight by extracting structured fields from plain
job-description text without additional LLM calls during shortlisting.
"""

import re

from models import JDRequirements

YEAR_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\+|plus)?\s*(?:years?|yrs?)", re.IGNORECASE)


def _clean_item(item: str) -> str:
    cleaned = re.sub(r"\s+", " ", item.strip("•-*: "))
    return cleaned.strip(".,;")


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        normalized = _clean_item(item)
        lowered = normalized.lower()
        if normalized and lowered not in seen:
            seen.add(lowered)
            result.append(normalized)
    return result


def _split_items(text: str) -> list[str]:
    if not text:
        return []

    if ":" in text:
        _, text = text.split(":", 1)

    text = text.strip()
    if not text:
        return []

    return [part for part in re.split(r"[;,]| / | and ", text) if part.strip()]


def _looks_like_header(line_lower: str) -> bool:
    return any(
        keyword in line_lower
        for keyword in (
            "required",
            "must have",
            "must-haves",
            "must have",
            "mandatory",
            "required qualifications",
            "preferred",
            "nice to have",
            "education",
            "experience",
            "role",
            "responsibilities",
        )
    )


def parse_job_description(jd_text: str) -> JDRequirements:
    """
    Extract structured signals from job description text.
    """
    req = JDRequirements()
    if not jd_text:
        return req

    lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
    section = "general"

    for line in lines:
        line_lower = line.lower()

        # Track the active JD section from headings
        if any(k in line_lower for k in ("required", "must", "mandatory", "essential", "core")):
            section = "required"
        elif any(k in line_lower for k in ("preferred", "nice to have", "nice-to-have", "bonus", "plus")):
            section = "preferred"
        elif any(k in line_lower for k in ("experience", "years", "yrs")):
            section = "experience"
        elif any(k in line_lower for k in ("education", "qualification", "degree", "certification", "certified")):
            section = "qualification"
        elif any(k in line_lower for k in ("role", "job title", "position")):
            section = "role"

        # Skip non-informative headings
        if _looks_like_header(line_lower) and len(line) < 120 and ":" in line:
            continue

        # Add role keywords from title/summary lines
        if section == "role" and len(line) > 8:
            req.role_keywords.extend(_split_items(line))

        # Extract experience requirement as max numeric years observed
        years = YEAR_PATTERN.findall(line)
        if years:
            try:
                req.required_experience_years = max(
                    float(req.required_experience_years or 0.0),
                    max(float(y) for y in years),
                )
            except ValueError:
                pass

        # Extract skills in required/preferred sections
        if section in {"required", "preferred"}:
            extracted = _split_items(line)
            if section == "required":
                req.required_skills.extend(_split_items(line))
            else:
                req.preferred_skills.extend(_split_items(line))
            continue

        # Extract qualifications section
        if section == "qualification":
            req.qualifications.extend(_split_items(line))
            continue

        # Fallback: capture inline skills mentions from any line
        if ":" in line and any(k in line_lower for k in ("skills", "technologies", "stack", "tools", "language")):
            req.required_skills.extend(_split_items(line))

    req.required_skills = _unique(req.required_skills)
    req.preferred_skills = _unique(req.preferred_skills)
    req.qualifications = _unique(req.qualifications)
    req.role_keywords = _unique(req.role_keywords)

    return req
