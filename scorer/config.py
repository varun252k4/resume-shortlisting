import os
from typing import Optional

# ── LLM (used only for 1-call summary per candidate) ──────────────────────
LLM_MODEL: str = os.getenv("LLM_MODEL", "groq/llama3-70b-8192")
LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY")
MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2500"))

# ── ChromaDB (local persistent vector store) ───────────────────────────────
# Default: stores DB next to scorer/ in a "chroma_db" folder
CHROMA_PATH: str = os.getenv(
    "CHROMA_PATH",
    os.path.join(os.path.dirname(__file__), "..", "chroma_db"),
)

# ── Embedding model ────────────────────────────────────────────────────────
# Uses fastembed locally — no API key needed, runs offline.
# Change EMBED_MODEL to swap embedding providers.
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
