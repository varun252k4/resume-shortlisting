"""
PostgreSQL vector store — replaces ChromaDB.

Embeddings are stored as FLOAT4[] columns in PostgreSQL.
Cosine similarity is computed in Python with numpy (already a transitive
dependency of fastembed). No pgvector extension required.

Two tables (created by schema.sql):
    jd_chunks      — JD text chunks per JD hash
    resume_chunks  — resume field embeddings per candidate hash
"""
import hashlib
from typing import Optional

import numpy as np

from db_postgres import get_pool
from embedder import embed_texts
from models import JDRequirements, ParsedResume


def _hash(text: str, length: int = 12) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:length]


def _safe_str(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _cosine(a, b) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(np.dot(va, vb) / denom) if denom else 0.0


def get_resume_id(resume: ParsedResume) -> str:
    """Stable candidate id for feedback and reuse across uploads/re-runs."""
    name  = _safe_str(resume.name)
    email = _safe_str(resume.contact.email)
    skills = ",".join(sorted({_safe_str(s) for s in resume.skills if s and s.strip()}))
    roles  = ",".join(
        sorted({_safe_str(e.role) for e in resume.work_experience if e.role and e.role.strip()})
    )
    return _hash(f"{name}|{email}|{roles}|{skills}", 16)


# ── JD chunking ────────────────────────────────────────────────────────────

def _chunk_jd(jd_text: str, requirements: Optional[JDRequirements] = None) -> list[dict]:
    chunks = []
    high_kw = {"required", "must", "mandatory", "essential", "minimum", "qualifications", "requirements"}
    low_kw  = {"preferred", "nice to have", "bonus", "plus", "good to have", "optional", "desired"}
    weight  = 0.8

    for line in [l.strip() for l in jd_text.splitlines() if l.strip()]:
        ll = line.lower()
        if any(k in ll for k in high_kw):
            weight = 1.0
        elif any(k in ll for k in low_kw):
            weight = 0.5
        if len(line) >= 8:
            chunks.append({"text": line, "weight": weight})

    if requirements:
        for s in requirements.required_skills:
            chunks.append({"text": f"Required skill: {s}", "weight": 1.0})
        for s in requirements.preferred_skills:
            chunks.append({"text": f"Preferred skill: {s}", "weight": 0.6})
        for q in requirements.qualifications:
            chunks.append({"text": f"Qualification: {q}", "weight": 0.9})
        for k in requirements.role_keywords:
            chunks.append({"text": f"Role keyword: {k}", "weight": 0.65})
        if requirements.required_experience_years is not None:
            chunks.append({
                "text": f"Minimum experience: {requirements.required_experience_years}+ years",
                "weight": 1.0,
            })
    return chunks


def _resume_documents(resume: ParsedResume) -> list[dict]:
    docs = []
    for skill in resume.skills:
        docs.append({"text": skill, "category": "skill"})
    for exp in resume.work_experience:
        text = f"{exp.role} at {exp.company}"
        if exp.description:
            text += f": {exp.description}"
        docs.append({"text": text, "category": "experience"})
    for edu in resume.education:
        docs.append({"text": f"{edu.degree} from {edu.institution}", "category": "education"})
    for cert in resume.certifications:
        docs.append({"text": cert, "category": "certification"})
    return docs


# ── Indexing ───────────────────────────────────────────────────────────────

async def index_jd(jd_text: str, requirements: Optional[JDRequirements] = None) -> str:
    """Embed JD chunks and insert into jd_chunks. No-op if already indexed."""
    jd_hash = _hash(jd_text)
    pool = get_pool()

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM jd_chunks WHERE jd_hash = $1 LIMIT 1", jd_hash
        )
        if exists:
            return jd_hash

    chunks = _chunk_jd(jd_text, requirements)
    if not chunks:
        return jd_hash

    texts      = [c["text"] for c in chunks]
    embeddings = await embed_texts(texts)

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO jd_chunks (jd_hash, chunk_index, content, embedding, weight)
            VALUES ($1, $2, $3, $4::float4[], $5)
            ON CONFLICT DO NOTHING
            """,
            [(jd_hash, i, chunks[i]["text"], embeddings[i], chunks[i]["weight"])
             for i in range(len(chunks))],
        )
    return jd_hash


async def index_resume(resume: ParsedResume) -> str:
    """Embed resume fields and upsert into resume_chunks. Returns resume_hash."""
    resume_hash = get_resume_id(resume)
    docs = _resume_documents(resume)
    if not docs:
        return resume_hash

    texts      = [d["text"] for d in docs]
    embeddings = await embed_texts(texts)

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM resume_chunks WHERE resume_hash = $1", resume_hash)
        await conn.executemany(
            """
            INSERT INTO resume_chunks (resume_hash, chunk_index, content, embedding, category)
            VALUES ($1, $2, $3, $4::float4[], $5)
            """,
            [(resume_hash, i, docs[i]["text"], embeddings[i], docs[i]["category"])
             for i in range(len(docs))],
        )
    return resume_hash


# ── Similarity scoring ─────────────────────────────────────────────────────

async def score_resume_against_jd(jd_hash: str, resume_hash: str, weightage: dict) -> dict:
    """
    Fetch JD and resume chunks from PostgreSQL, compute pairwise cosine
    similarity in Python, and return weighted scores.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        jd_rows  = await conn.fetch(
            "SELECT content, embedding, weight FROM jd_chunks WHERE jd_hash = $1", jd_hash
        )
        res_rows = await conn.fetch(
            "SELECT content, embedding, category FROM resume_chunks WHERE resume_hash = $1", resume_hash
        )

    if not jd_rows or not res_rows:
        return _empty_scores()

    jd_data = [
        {"text": r["content"], "emb": list(r["embedding"]), "weight": float(r["weight"])}
        for r in jd_rows
    ]

    THRESHOLD = 0.72
    category_scores: dict[str, list[float]] = {
        "skill": [], "experience": [], "education": [], "certification": []
    }
    matched_pairs: list[dict] = []

    for row in res_rows:
        category = row["category"]
        res_emb  = list(row["embedding"])
        best_sim, best_text, best_weight = 0.0, "", 0.8

        for jd in jd_data:
            sim = _cosine(res_emb, jd["emb"])
            if sim > best_sim:
                best_sim, best_text, best_weight = sim, jd["text"], jd["weight"]

        category_scores.setdefault(category, []).append(best_sim * best_weight)

        if best_sim >= THRESHOLD:
            matched_pairs.append({
                "resume_text": row["content"],
                "jd_text": best_text,
                "similarity": round(best_sim, 3),
                "category": category,
            })

    # Reverse: find high-weight JD requirements the resume didn't cover
    missing_reqs: list[str] = []
    for jd in jd_data:
        if jd["weight"] < 1.0:
            continue
        best = max((_cosine(jd["emb"], list(r["embedding"])) for r in res_rows), default=0.0)
        if best < THRESHOLD:
            words   = jd["text"].split()[:7]
            snippet = " ".join(words) + ("..." if len(words) >= 7 else "")
            if snippet not in missing_reqs:
                missing_reqs.append(snippet)

    def avg(lst: list[float]) -> float:
        return round((sum(lst) / len(lst)) * 100, 1) if lst else 0.0

    skill_score = avg(category_scores["skill"])
    exp_score   = avg(category_scores["experience"])
    edu_score   = avg(category_scores["education"])
    cert_score  = avg(category_scores["certification"])

    total = (
        skill_score * weightage.get("skills", 0.4)
        + exp_score * weightage.get("experience", 0.3)
        + edu_score * weightage.get("education", 0.2)
        + cert_score * weightage.get("certifications", 0.1)
    )

    return {
        "total_score": round(min(total, 100.0), 1),
        "breakdown": {
            "skills":         skill_score,
            "experience":     exp_score,
            "education":      edu_score,
            "certifications": cert_score,
        },
        "matched_pairs": matched_pairs,
        "missing":       missing_reqs,
    }


def _empty_scores() -> dict:
    return {
        "total_score": 0.0,
        "breakdown": {"skills": 0.0, "experience": 0.0, "education": 0.0, "certifications": 0.0},
        "matched_pairs": [],
        "missing": [],
    }


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