"""OpenAI embedding client helpers for document chunks and retrieval queries."""

from __future__ import annotations

from typing import Sequence

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_BATCH_SIZE = 64


def _sanitize_text(text: str) -> str:
    """Normalize input text for the embedding API."""

    return " ".join(text.replace("\x00", " ").split())


def _get_openai_client():
    """Create an OpenAI client lazily so import-time stays lightweight."""

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("The 'openai' package is required for embeddings.") from exc

    return OpenAI()


def embed_texts(
    texts: Sequence[str],
    *,
    model: str = EMBEDDING_MODEL,
    batch_size: int = EMBEDDING_BATCH_SIZE,
) -> list[list[float]]:
    """Embed arbitrary texts using batched OpenAI embedding requests."""

    if not texts:
        return []

    client = _get_openai_client()
    sanitized_texts = [_sanitize_text(text) for text in texts]
    embeddings: list[list[float]] = []

    for start in range(0, len(sanitized_texts), batch_size):
        batch = sanitized_texts[start : start + batch_size]
        response = client.embeddings.create(
            model=model,
            input=batch,
        )
        embeddings.extend([item.embedding for item in response.data])

    return embeddings


def embed_chunks(chunks: list[dict[str, object]]) -> list[list[float]]:
    """Embed chunk payloads based on their chunk_text field."""

    texts = [str(chunk["chunk_text"]) for chunk in chunks]
    return embed_texts(texts)
