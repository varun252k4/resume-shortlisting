"""
Embedder — wraps fastembed for local, offline text embeddings.
No API key required. Model is downloaded on first use (~130MB for bge-small).
"""
import os
from typing import Optional

# Use HuggingFace mirror in case hf.co is blocked/throttled
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from fastembed import TextEmbedding
from config import EMBED_MODEL

# Singleton — loaded once per process
_model: Optional[TextEmbedding] = None


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=EMBED_MODEL)
    return _model


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of strings. Returns a list of float vectors.
    fastembed is synchronous internally but fast enough for our use.
    """
    model = _get_model()
    embeddings = list(model.embed(texts))
    return [e.tolist() for e in embeddings]
