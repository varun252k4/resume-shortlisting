import os
from typing import Optional

#  LLM (used only for 1-call summary per candidate) 
LLM_MODEL: str = os.getenv("LLM_MODEL", "groq/llama3-70b-8192")
LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY")
MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2500"))

#  Embedding model (fastembed — local, no API key required) 
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")

#  PostgreSQL (single database for all data + vector store) 
POSTGRES_DSN: str = os.getenv(
    "POSTGRES_DSN",
    "postgresql://postgres:postgres@localhost:5432/resume_shortlisting",
)
