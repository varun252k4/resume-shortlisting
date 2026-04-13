"""
ChromaDB vector store.

Two collections per job posting:
  jd_{id}       — JD text chunks (indexed once)
  resume_{id}   — resume field embeddings (indexed per candidate)

Both sides live in vector space. Scoring = querying one against the other.
"""
import hashlib
from typing import Optional

import chromadb
from chromadb.config import Settings

from scorer.config import CHROMA_PATH
from scorer.embedder import embed_texts
from scorer.models import JDRequirements, ParsedResume

_client = chromadb.PersistentClient(
    path=CHROMA_PATH,
    settings=Settings(anonymized_telemetry=False),
)


def _hash(text: str, length: int = 12) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:length]


def _safe_str(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def get_resume_id(resume: ParsedResume) -> str:
    """
    Stable candidate id for feedback and reuse across uploads/re-runs.
    """
    name = _safe_str(resume.name)
    email = _safe_str(resume.contact.email)
    skills = ",".join(sorted({_safe_str(s) for s in resume.skills if s and s.strip()}))
    roles = ",".join(
        sorted({_safe_str(exp.role) for exp in resume.work_experience if exp.role and exp.role.strip()})
    )
    identifier = f"{name}|{email}|{roles}|{skills}"
    return _hash(identifier, 16)


# ── JD Indexing (raw text → chunks → vectors) ─────────────────────────────

def _chunk_jd(jd_text: str, requirements: Optional[JDRequirements] = None) -> list[dict]:
    """
    Split JD into meaningful chunks with metadata tags.
    No LLM needed — we use simple line/section splitting.
    Each chunk gets a weight: requirements sections score higher.
    """
    chunks = []
    high_weight_keywords = {
        "required", "must", "mandatory", "essential",
        "minimum", "qualifications", "requirements",
    }
    low_weight_keywords = {
        "preferred", "nice to have", "bonus", "plus",
        "good to have", "optional", "desired",
    }

    lines = [l.strip() for l in jd_text.splitlines() if l.strip()]
    current_weight = 0.8  # default weight

    for line in lines:
        line_lower = line.lower()

        # Adjust weight based on section heading
        if any(kw in line_lower for kw in high_weight_keywords):
            current_weight = 1.0
        elif any(kw in line_lower for kw in low_weight_keywords):
            current_weight = 0.5

        # Skip very short lines (headings, bullets alone)
        if len(line) < 8:
            continue

        chunks.append({
            "text": line,
            "weight": current_weight,
        })

    # Explicit requirement injection from structured parsing
    if requirements:
        req_chunks = []
        for skill in requirements.required_skills:
            req_chunks.append({"text": f"Required skill: {skill}", "weight": 1.0})
        for skill in requirements.preferred_skills:
            req_chunks.append({"text": f"Preferred skill: {skill}", "weight": 0.6})
        for qual in requirements.qualifications:
            req_chunks.append({"text": f"Qualification: {qual}", "weight": 0.9})
        for keyword in requirements.role_keywords:
            req_chunks.append({"text": f"Role keyword: {keyword}", "weight": 0.65})
        if requirements.required_experience_years is not None:
            req_chunks.append({
                "text": f"Minimum experience: {requirements.required_experience_years}+ years",
                "weight": 1.0,
            })
        chunks.extend(req_chunks)

    return chunks


async def index_jd(jd_text: str, requirements: Optional[JDRequirements] = None) -> str:
    """
    Embed raw JD text chunks and store in ChromaDB.
    Returns jd_id. No-op if already indexed.
    """
    jd_id = _hash(jd_text)
    collection_name = f"jd_{jd_id}"

    existing = [c.name for c in _client.list_collections()]
    if collection_name in existing:
        return jd_id

    chunks = _chunk_jd(jd_text, requirements)
    if not chunks:
        return jd_id

    texts = [c["text"] for c in chunks]
    embeddings = await embed_texts(texts)

    collection = _client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        documents=texts,
        embeddings=embeddings,
        metadatas=[{"weight": c["weight"]} for c in chunks],
        ids=[f"chunk_{i}" for i in range(len(chunks))],
    )
    return jd_id


# ── Resume Indexing (structured fields → vectors) ─────────────────────────

def _resume_documents(resume: ParsedResume) -> list[dict]:
    """
    Convert resume structured fields into embeddable text documents.
    Each field type gets a category tag for weighted scoring later.
    """
    docs = []

    # Skills — individual items, category: skill
    for skill in resume.skills:
        docs.append({"text": skill, "category": "skill"})

    # Work experience — role + company + description, category: experience
    for exp in resume.work_experience:
        text = f"{exp.role} at {exp.company}"
        if exp.description:
            text += f": {exp.description}"
        docs.append({"text": text, "category": "experience"})

    # Education — degree + institution, category: education
    for edu in resume.education:
        docs.append({
            "text": f"{edu.degree} from {edu.institution}",
            "category": "education",
        })

    # Certifications — individual items, category: certification
    for cert in resume.certifications:
        docs.append({"text": cert, "category": "certification"})

    return docs


async def index_resume(resume: ParsedResume) -> str:
    """
    Embed resume fields and store in ChromaDB.
    Returns resume_id. Overwrites if same candidate re-indexed.
    """
    resume_id = get_resume_id(resume)
    collection_name = f"resume_{resume_id}"

    # Always re-index (resume may be updated)
    existing = [c.name for c in _client.list_collections()]
    if collection_name in existing:
        _client.delete_collection(collection_name)

    docs = _resume_documents(resume)
    if not docs:
        return resume_id

    texts = [d["text"] for d in docs]
    embeddings = await embed_texts(texts)

    collection = _client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        documents=texts,
        embeddings=embeddings,
        metadatas=[{"category": d["category"]} for d in docs],
        ids=[f"{d['category']}_{i}" for i, d in enumerate(docs)],
    )
    return resume_id


# ── Similarity Scoring ─────────────────────────────────────────────────────

async def score_resume_against_jd(
    jd_id: str,
    resume_id: str,
    weightage: dict,          # {"skills": 0.4, "experience": 0.3, ...}
) -> dict:
    """
    Query resume vectors against JD vectors.
    For each resume document, find closest JD chunk → weighted similarity.

    Returns per-category scores and matched/missing details.
    """
    jd_collection   = _client.get_collection(f"jd_{jd_id}")
    res_collection  = _client.get_collection(f"resume_{resume_id}")

    # Pull all resume documents with their embeddings
    res_data = res_collection.get(include=["documents", "embeddings", "metadatas"])

    if not res_data["documents"]:
        return _empty_scores()

    category_scores: dict[str, list[float]] = {
        "skill": [], "experience": [], "education": [], "certification": []
    }
    matched_pairs = []
    THRESHOLD = 0.72

    for doc, embedding, meta in zip(
        res_data["documents"],
        res_data["embeddings"],
        res_data["metadatas"],
    ):
        category = meta.get("category", "skill")

        # Query this resume chunk against JD chunks
        results = jd_collection.query(
            query_embeddings=[embedding],
            n_results=3,
            include=["documents", "distances", "metadatas"],
        )

        if not results["distances"][0]:
            continue

        # Best match: 1 - cosine distance = cosine similarity
        best_sim   = 1 - results["distances"][0][0]
        best_chunk = results["documents"][0][0]
        jd_weight  = results["metadatas"][0][0].get("weight", 0.8)

        weighted_sim = best_sim * jd_weight
        category_scores[category].append(weighted_sim)

        if best_sim >= THRESHOLD:
            matched_pairs.append({
                "resume_text": doc,
                "jd_text": best_chunk,
                "similarity": round(best_sim, 3),
                "category": category,
            })

    # Reverse query: find what JD required that the candidate missed
    missing_reqs = []
    jd_data = jd_collection.get(include=["documents", "embeddings", "metadatas"])
    if jd_data["documents"]:
        for jd_doc, jd_emb, jd_meta in zip(jd_data["documents"], jd_data["embeddings"], jd_data["metadatas"]):
            # Only check highly weighted JD chunks (the core requirements)
            if jd_meta.get("weight", 0.8) >= 1.0:
                res = res_collection.query(query_embeddings=[jd_emb], n_results=1, include=["distances"])
                if res["distances"][0]:
                    sim = 1 - res["distances"][0][0]
                    if sim < THRESHOLD:
                        # Extract just the first few words to keep it looking like a "skill/req"
                        words = jd_doc.split()[:7]
                        snippet = " ".join(words) + ("..." if len(words) >= 7 else "")
                        # avoid duplicates
                        if snippet not in missing_reqs:
                            missing_reqs.append(snippet)

    # Average similarity per category → 0-100
    def avg(lst): return round((sum(lst) / len(lst)) * 100, 1) if lst else 0.0

    skill_score  = avg(category_scores["skill"])
    exp_score    = avg(category_scores["experience"])
    edu_score    = avg(category_scores["education"])
    cert_score   = avg(category_scores["certification"])

    total = (
        skill_score  * weightage.get("skills", 0.4)        +
        exp_score    * weightage.get("experience", 0.3)     +
        edu_score    * weightage.get("education", 0.2)      +
        cert_score   * weightage.get("certifications", 0.1)
    )

    return {
        "total_score": round(min(total, 100.0), 1),
        "breakdown": {
            "skills": skill_score,
            "experience": exp_score,
            "education": edu_score,
            "certifications": cert_score,
        },
        "matched_pairs": matched_pairs,
        "missing": missing_reqs,
    }


def _empty_scores() -> dict:
    return {
        "total_score": 0.0,
        "breakdown": {"skills": 0.0, "experience": 0.0, "education": 0.0, "certifications": 0.0},
        "matched_pairs": [],
        "missing": [],
    }