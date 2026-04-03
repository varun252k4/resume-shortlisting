import os

# ── AI Provider Configuration ──────────────────────────────────────────────
# Set these environment variables to switch providers with zero code changes.
#
# Examples:
#   Groq:     LLM_MODEL=groq/llama3-70b-8192       + GROQ_API_KEY=...
#   Claude:   LLM_MODEL=anthropic/claude-sonnet-4-20250514  + ANTHROPIC_API_KEY=...
#   OpenAI:   LLM_MODEL=openai/gpt-4o              + OPENAI_API_KEY=...
#   Mistral:  LLM_MODEL=mistral/mistral-large-latest + MISTRAL_API_KEY=...
#   Ollama:   LLM_MODEL=ollama/llama3              (no key needed)
# ──────────────────────────────────────────────────────────────────────────

LLM_MODEL: str = os.getenv("LLM_MODEL", "groq/llama3-70b-8192")
LLM_API_KEY: str | None = os.getenv("LLM_API_KEY")  # optional override
MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "2500"))
