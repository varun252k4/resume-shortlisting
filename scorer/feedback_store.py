"""
Persistent lightweight feedback loop used to calibrate future shortlist scoring.

The intent is practical and transparent:
- Employers submit corrections after reviewing a scored candidate.
- We compute a mean offset (human_score - ai_score) per job posting.
- That offset is then applied as a calibration factor on subsequent candidates.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

FEEDBACK_FILE = os.path.join(os.path.dirname(__file__), "feedback_store.json")
MAX_FEEDBACK_ENTRIES = 2000
RECALIBRATE_TTL_SECONDS = 24 * 60 * 60


def _default_state() -> dict[str, Any]:
    return {"entries": [], "job_calibration": {}}


def _load_state() -> dict[str, Any]:
    if not os.path.exists(FEEDBACK_FILE):
        return _default_state()
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return _default_state()


def _save_state(state: dict[str, Any]) -> None:
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _derive_jd_id(jd_text: str) -> str:
    return hashlib.md5(jd_text.encode()).hexdigest()[:12]


def _coerce_flag_match(flag_value: Any) -> str:
    if hasattr(flag_value, "value"):
        return str(flag_value.value)
    return str(flag_value)


def _to_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)


def _job_alignment(jd_feedback: list[dict[str, Any]]) -> float:
    if not jd_feedback:
        return 100.0
    total = len(jd_feedback)
    matches = 0
    for entry in jd_feedback:
        if _coerce_flag_match(entry.get("ai_flag")) == _coerce_flag_match(entry.get("employer_flag")):
            matches += 1
    return round((matches / total) * 100, 1)


def _job_offset(jd_feedback: list[dict[str, Any]]) -> float:
    if not jd_feedback:
        return 0.0

    deltas = []
    for entry in jd_feedback:
        deltas.append(
            float(entry.get("employer_total_score", 0.0)) - float(entry.get("ai_total_score", 0.0))
        )
    if not deltas:
        return 0.0
    raw = sum(deltas) / len(deltas)
    return round(max(min(raw, 12.0), -12.0), 2)


def _recompute_calibration(state: dict[str, Any], jd_id: str) -> None:
    jd_feedback = [entry for entry in state["entries"] if entry.get("jd_id") == jd_id]
    calibration = {
        "feedback_count": len(jd_feedback),
        "feedback_alignment_pct": _job_alignment(jd_feedback),
        "calibration_offset": _job_offset(jd_feedback),
        "last_recalibrated_at": _to_iso_now(),
    }
    state["job_calibration"][jd_id] = calibration


def add_feedback_record(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """
    Persist feedback and return (jd_id, calibration) for the target JD.
    """
    state = _load_state()

    jd_id = payload.get("jd_id") or _derive_jd_id((payload.get("jd_text") or "").strip())
    now = _to_iso_now()
    record = {
        "feedback_id": payload.get("feedback_id"),
        "jd_id": jd_id,
        "resume_id": payload.get("resume_id"),
        "resume_name": payload.get("resume_name"),
        "ai_total_score": payload.get("ai_total_score", 0.0),
        "ai_flag": _coerce_flag_match(payload.get("ai_flag")),
        "employer_total_score": payload.get("employer_total_score", 0.0),
        "employer_flag": _coerce_flag_match(payload.get("employer_flag")),
        "created_at": now,
        "notes": payload.get("notes"),
    }

    state["entries"].append(record)
    state["entries"] = state["entries"][-MAX_FEEDBACK_ENTRIES:]

    _recompute_calibration(state, jd_id)
    _save_state(state)

    calibration = state["job_calibration"][jd_id]
    return jd_id, calibration


def get_calibration(jd_id: str) -> dict[str, Any]:
    state = _load_state()
    calibration = state.get("job_calibration", {}).get(jd_id)

    if not calibration:
        return {
            "jd_id": jd_id,
            "feedback_count": 0,
            "feedback_alignment_pct": 0.0,
            "calibration_offset": 0.0,
            "last_recalibrated_at": _to_iso_now(),
            "stale": False,
        }

    last = _parse_iso(calibration.get("last_recalibrated_at", _to_iso_now()))
    stale = datetime.now(timezone.utc) - last > timedelta(seconds=RECALIBRATE_TTL_SECONDS)
    if stale:
        _recompute_calibration(state, jd_id)
        _save_state(state)
        calibration = state["job_calibration"][jd_id]

    calibration = dict(calibration)
    calibration["jd_id"] = jd_id
    calibration["stale"] = stale
    return calibration
