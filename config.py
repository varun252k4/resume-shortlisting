"""
Central configuration — reads from environment variables.
Copy .env.example to .env and fill in the values, or export them in your shell.

Required env vars:
  LLM_API_KEY   — API key for the LLM provider (Groq, OpenAI, etc.)
  LLM_MODEL     — LiteLLM model string, e.g. "groq/llama-3.3-70b-versatile"

Optional env vars:
  EMBED_MODEL   — fastembed model name (default: BAAI/bge-small-en-v1.5)
  CHROMA_PATH   — directory for ChromaDB persistence (default: .chroma)
  MAX_TOKENS    — max tokens for LLM extraction calls (default: 2048)
"""

import os

# ── LLM ───────────────────────────────────────────────────────────────────
LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "groq/llama-3.3-70b-versatile")
MAX_TOKENS: int = int(os.environ.get("MAX_TOKENS", "2048"))

# ── Embeddings & Vector store ─────────────────────────────────────────────
EMBED_MODEL: str = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
CHROMA_PATH: str = os.environ.get("CHROMA_PATH", os.path.join(os.path.dirname(__file__), ".chroma"))
