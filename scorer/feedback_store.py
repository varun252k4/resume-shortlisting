"""
Feedback-loop calibration store — backed by PostgreSQL.

Tables used (defined in schema.sql):
    ai_feedback          — raw employer score corrections per JD
    ai_job_calibration   — per-JD aggregated calibration state

The mean offset (employer_score − ai_score) per JD is stored and
automatically applied on subsequent scoring calls for that JD.
"""

import hashlib
from datetime import datetime, timezone
from typing import Any

from db_postgres import get_pool

MAX_OFFSET = 12.0


def _derive_jd_id(jd_text: str) -> str:
    return hashlib.md5(jd_text.encode()).hexdigest()[:12]


def _to_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_flag(flag_value: Any) -> str:
    if hasattr(flag_value, "value"):
        return str(flag_value.value)
    return str(flag_value)


async def _recompute_and_save(jd_id: str) -> dict[str, Any]:
    """Aggregate feedback rows for jd_id, update ai_job_calibration, return calibration dict."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT ai_total_score, employer_total_score, ai_flag, employer_flag "
            "FROM ai_feedback WHERE jd_id = $1",
            jd_id,
        )
        count = len(rows)
        if count == 0:
            offset, alignment = 0.0, 100.0
        else:
            deltas = [float(r["employer_total_score"]) - float(r["ai_total_score"]) for r in rows]
            raw = sum(deltas) / len(deltas)
            offset = round(max(min(raw, MAX_OFFSET), -MAX_OFFSET), 2)
            matches = sum(1 for r in rows if r["ai_flag"] == r["employer_flag"])
            alignment = round((matches / count) * 100, 1)

        await conn.execute(
            """
            INSERT INTO ai_job_calibration
                (jd_id, feedback_count, feedback_alignment_pct, calibration_offset, last_recalibrated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (jd_id) DO UPDATE
              SET feedback_count          = EXCLUDED.feedback_count,
                  feedback_alignment_pct  = EXCLUDED.feedback_alignment_pct,
                  calibration_offset      = EXCLUDED.calibration_offset,
                  last_recalibrated_at    = NOW()
            """,
            jd_id, count, alignment, offset,
        )
    return {
        "jd_id": jd_id,
        "feedback_count": count,
        "feedback_alignment_pct": alignment,
        "calibration_offset": offset,
        "last_recalibrated_at": _to_iso_now(),
    }


async def add_feedback_record(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Persist one feedback entry and return (jd_id, updated_calibration)."""
    jd_id = payload.get("jd_id") or _derive_jd_id((payload.get("jd_text") or "").strip())
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ai_feedback
                (jd_id, resume_id, resume_name,
                 ai_total_score, employer_total_score, ai_flag, employer_flag)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            jd_id,
            payload.get("resume_id"),
            payload.get("resume_name"),
            float(payload.get("ai_total_score", 0.0)),
            float(payload.get("employer_total_score", 0.0)),
            _coerce_flag(payload.get("ai_flag", "")),
            _coerce_flag(payload.get("employer_flag", "")),
        )
    calibration = await _recompute_and_save(jd_id)
    return jd_id, calibration


async def get_calibration(jd_id: str) -> dict[str, Any]:
    """Return the current calibration state for a JD (offset = 0 if no feedback yet)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT jd_id, feedback_count, feedback_alignment_pct, "
            "calibration_offset, last_recalibrated_at "
            "FROM ai_job_calibration WHERE jd_id = $1",
            jd_id,
        )
    if row is None:
        return {
            "jd_id": jd_id,
            "feedback_count": 0,
            "feedback_alignment_pct": 100.0,
            "calibration_offset": 0.0,
            "last_recalibrated_at": _to_iso_now(),
        }
    result = dict(row)
    # asyncpg returns datetimes as datetime objects; stringify for JSON serialisation
    if isinstance(result.get("last_recalibrated_at"), datetime):
        result["last_recalibrated_at"] = result["last_recalibrated_at"].isoformat()
    return result
