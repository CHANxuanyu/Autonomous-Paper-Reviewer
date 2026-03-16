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


def _window_token_ranges(
    total_tokens: int,
    *,
    chunk_size_tokens: int,
    overlap_tokens: int,
) -> list[tuple[int, int]]:
    """Return token index windows for a chunking pass."""

    if total_tokens <= 0:
        return []
    if total_tokens <= chunk_size_tokens:
        return [(0, total_tokens)]

    step = max(1, chunk_size_tokens - overlap_tokens)
    windows: list[tuple[int, int]] = []
    for start in range(0, total_tokens, step):
        end = min(start + chunk_size_tokens, total_tokens)
        windows.append((start, end))
        if end >= total_tokens:
            break
    return windows


def _distance_to_window(position: int, start: int, end: int) -> int:
    """Measure how far an anchor lies from a token window."""

    if start <= position < end:
        return 0
    if position < start:
        return start - position
    return position - end + 1


def _build_synthetic_visual_chunk(
    *,
    page_number: int | None,
    fallback_section: str | None,
    visual_block: dict[str, Any],
) -> dict[str, Any]:
    """Create a small anchor chunk when a visual has no free nearby text chunk."""

    anchor_text = str(visual_block.get("caption_or_context") or "").strip()
    if not anchor_text:
        category = str(visual_block.get("category") or "Visual")
        anchor_text = f"{category} reference on page {page_number or 'unknown'}."

    anchor_tokens = _tokenize(anchor_text)
    if len(anchor_tokens) > DEFAULT_CHUNK_SIZE_TOKENS:
        anchor_text = _detokenize(anchor_tokens[:DEFAULT_CHUNK_SIZE_TOKENS])

    return {
        "chunk_text": anchor_text,
        "page_number": page_number,
        "section_name": _detect_section_name(anchor_text, fallback_section),
        "token_count": _estimate_token_count(anchor_text),
        "linked_image_path": visual_block.get("image_path"),
    }


def _link_visuals_to_page_chunks(
    *,
    page_number: int | None,
    page_chunks: list[dict[str, Any]],
    block_spans: list[dict[str, Any]],
    visual_blocks: list[dict[str, Any]],
    fallback_section: str | None,
) -> list[dict[str, Any]]:
    """Attach each extracted image/table to the closest chunk on the same page."""

    if not visual_blocks:
        return page_chunks

    order_to_span = {span["order"]: span for span in block_spans}
    linked_chunks = list(page_chunks)

    for visual_block in visual_blocks:
        image_path = visual_block.get("image_path")
        if not image_path:
            continue

        anchor_order = visual_block.get("anchor_text_order")
        anchor_span = order_to_span.get(anchor_order)
        if anchor_span is None:
            linked_chunks.append(
                _build_synthetic_visual_chunk(
                    page_number=page_number,
                    fallback_section=fallback_section,
                    visual_block=visual_block,
                )
            )
            continue

        anchor_position = int(anchor_span["end"])

        available_chunks = [chunk for chunk in linked_chunks if chunk.get("linked_image_path") is None]
        candidate_chunks = available_chunks or linked_chunks

        if not candidate_chunks:
            linked_chunks.append(
                _build_synthetic_visual_chunk(
                    page_number=page_number,
                    fallback_section=fallback_section,
                    visual_block=visual_block,
                )
            )
            continue

        best_chunk = min(
            candidate_chunks,
            key=lambda chunk: (
                _distance_to_window(
                    anchor_position,
                    int(chunk.get("_token_start", 0)),
                    int(chunk.get("_token_end", 0)),
                ),
                abs(
                    int(anchor_order or 0)
                    - int(
                        (
                            int(chunk.get("_block_order_start", 0))
                            + int(chunk.get("_block_order_end", 0))
                        )
                        / 2
                    )
                ),
            ),
        )

        if best_chunk.get("linked_image_path") is None:
            best_chunk["linked_image_path"] = image_path
        else:
            linked_chunks.append(
                _build_synthetic_visual_chunk(
                    page_number=page_number,
                    fallback_section=fallback_section,
                    visual_block=visual_block,
                )
            )

    return linked_chunks


def split_document(parsed_document: dict[str, Any]) -> list[dict[str, Any]]:
    """Split parsed page text into chunk payloads ready for vector storage."""

    pages = parsed_document.get("pages") or []
    if not pages and parsed_document.get("full_text"):
        pages = [{"page_number": 1, "text": parsed_document["full_text"]}]

    chunk_payloads: list[dict[str, Any]] = []
    current_section: str | None = None

    for page in pages:
        page_number = page.get("page_number")
        text_blocks = list(page.get("text_blocks") or [])
        visual_blocks = list(page.get("visual_blocks") or [])
        page_text = str(page.get("text") or "").strip()
        if not page_text and not visual_blocks:
            continue

        page_chunk_payloads: list[dict[str, Any]] = []
        block_spans: list[dict[str, Any]] = []

        if text_blocks:
            page_tokens: list[str] = []
            for block in text_blocks:
                block_text = str(block.get("text") or "").strip()
                if not block_text:
                    continue

                current_section = _detect_section_name(block_text, current_section)
                block_tokens = _tokenize(block_text)
                if not block_tokens:
                    continue

                token_start = len(page_tokens)
                page_tokens.extend(block_tokens)
                token_end = len(page_tokens)
                block_spans.append(
                    {
                        "order": int(block.get("order", token_end)),
                        "start": token_start,
                        "end": token_end,
                        "section_name": current_section,
                        "text": block_text,
                    }
                )

            for token_start, token_end in _window_token_ranges(
                len(page_tokens),
                chunk_size_tokens=DEFAULT_CHUNK_SIZE_TOKENS,
                overlap_tokens=DEFAULT_CHUNK_OVERLAP_TOKENS,
            ):
                chunk_text = _detokenize(page_tokens[token_start:token_end])
                if not chunk_text:
                    continue

                covering_blocks = [
                    span
                    for span in block_spans
                    if span["end"] > token_start and span["start"] < token_end
                ]
                section_name = (
                    covering_blocks[-1]["section_name"] if covering_blocks else current_section
                )
                block_order_start = (
                    int(covering_blocks[0]["order"]) if covering_blocks else token_start
                )
                block_order_end = int(covering_blocks[-1]["order"]) if covering_blocks else token_end

                page_chunk_payloads.append(
                    {
                        "chunk_text": chunk_text,
                        "page_number": page_number,
                        "section_name": section_name,
                        "token_count": _estimate_token_count(chunk_text),
                        "linked_image_path": None,
                        "_token_start": token_start,
                        "_token_end": token_end,
                        "_block_order_start": block_order_start,
                        "_block_order_end": block_order_end,
                    }
                )
        elif page_text:
            current_section = _detect_section_name(page_text, current_section)
            for chunk_text in _split_text_to_chunks(
                page_text,
                chunk_size_tokens=DEFAULT_CHUNK_SIZE_TOKENS,
                overlap_tokens=DEFAULT_CHUNK_OVERLAP_TOKENS,
            ):
                page_chunk_payloads.append(
                    {
                        "chunk_text": chunk_text,
                        "page_number": page_number,
                        "section_name": current_section,
                        "token_count": _estimate_token_count(chunk_text),
                        "linked_image_path": None,
                    }
                )

        page_chunk_payloads = _link_visuals_to_page_chunks(
            page_number=page_number,
            page_chunks=page_chunk_payloads,
            block_spans=block_spans,
            visual_blocks=visual_blocks,
            fallback_section=current_section,
        )

        for page_chunk in page_chunk_payloads:
            page_chunk.pop("_token_start", None)
            page_chunk.pop("_token_end", None)
            page_chunk.pop("_block_order_start", None)
            page_chunk.pop("_block_order_end", None)
            page_chunk["chunk_index"] = len(chunk_payloads)
            chunk_payloads.append(page_chunk)

    return chunk_payloads
