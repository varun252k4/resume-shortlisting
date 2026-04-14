"""
Motor async MongoDB client singleton.

Collections:
    parsed_resumes  — candidate resume documents + metadata
    ai_jobs         — job postings created through the AI service
    ai_rankings     — AI-generated ranking results per job
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from typing import Optional

_client: Optional[AsyncIOMotorClient] = None
_db_name: str = "resume_shortlisting"


def init_mongo(uri: str, db_name: str = "resume_shortlisting") -> None:
    global _client, _db_name
    _client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=5000)
    _db_name = db_name


async def close_mongo() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


def _get_db():
    if _client is None:
        raise RuntimeError(
            "MongoDB not initialised. "
            "Set MONGO_URI in your environment and restart the server."
        )
    return _client[_db_name]


def resumes_col() -> AsyncIOMotorCollection:
    """Parsed resume documents."""
    return _get_db()["parsed_resumes"]


def jobs_col() -> AsyncIOMotorCollection:
    """Job postings created via the AI service."""
    return _get_db()["ai_jobs"]


def rankings_col() -> AsyncIOMotorCollection:
    """AI-generated ranking results, keyed by job_id."""
    return _get_db()["ai_rankings"]
