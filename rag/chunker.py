"""Document chunking utilities for page-aware RAG ingestion."""

from __future__ import annotations

import re
from typing import Any

DEFAULT_CHUNK_SIZE_TOKENS = 1000
DEFAULT_CHUNK_OVERLAP_TOKENS = 200

SECTION_HEADING_PATTERN = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*)?\s*"
    r"(abstract|introduction|background|related work|method|methods|approach|"
    r"experimental setup|experiments|results|discussion|limitations|conclusion|appendix)"
    r"\s*$",
    re.IGNORECASE,
)

TOKEN_PATTERN = re.compile(r"\S+")


def _tokenize(text: str) -> list[str]:
    """Split text into coarse word-like tokens."""

    return TOKEN_PATTERN.findall(text)


def _detokenize(tokens: list[str]) -> str:
    """Rebuild text from tokens for embedding and storage."""

    return " ".join(tokens).strip()


def _estimate_token_count(text: str) -> int:
    """Estimate token count with a simple whitespace tokenizer."""

    return len(_tokenize(text))


def _detect_section_name(text: str, current_section: str | None) -> str | None:
    """Infer the active section name from heading-like lines."""

    for line in text.splitlines()[:12]:
        candidate = " ".join(line.split()).strip(" :.-")
        if not candidate:
            continue
        match = SECTION_HEADING_PATTERN.match(candidate)
        if match:
            return match.group(1).title()

    return current_section


def _split_text_to_chunks(
    text: str,
    *,
    chunk_size_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Split text into overlapping token windows."""

    tokens = _tokenize(text)
    if not tokens:
        return []

    if len(tokens) <= chunk_size_tokens:
        return [_detokenize(tokens)]

    step = max(1, chunk_size_tokens - overlap_tokens)
    chunks: list[str] = []
    for start in range(0, len(tokens), step):
        window = tokens[start : start + chunk_size_tokens]
        if not window:
            break
        chunks.append(_detokenize(window))
        if start + chunk_size_tokens >= len(tokens):
            break
    return chunks


def split_document(parsed_document: dict[str, Any]) -> list[dict[str, Any]]:
    """Split parsed page text into chunk payloads ready for vector storage."""

    pages = parsed_document.get("pages") or []
    if not pages and parsed_document.get("full_text"):
        pages = [{"page_number": 1, "text": parsed_document["full_text"]}]

    chunk_payloads: list[dict[str, Any]] = []
    current_section: str | None = None

    for page in pages:
        page_number = page.get("page_number")
        page_text = str(page.get("text") or "").strip()
        if not page_text:
            continue

        current_section = _detect_section_name(page_text, current_section)
        page_chunks = _split_text_to_chunks(
            page_text,
            chunk_size_tokens=DEFAULT_CHUNK_SIZE_TOKENS,
            overlap_tokens=DEFAULT_CHUNK_OVERLAP_TOKENS,
        )

        for chunk_text in page_chunks:
            chunk_payloads.append(
                {
                    "chunk_text": chunk_text,
                    "page_number": page_number,
                    "section_name": current_section,
                    "chunk_index": len(chunk_payloads),
                    "token_count": _estimate_token_count(chunk_text),
                }
            )

    return chunk_payloads
