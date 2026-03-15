"""PDF parsing utilities for extracting text and lightweight metadata."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_pdf_path(file_url: str) -> Path:
    """Resolve an absolute or project-relative PDF path."""

    candidate = Path(file_url)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _normalize_whitespace(text: str) -> str:
    """Collapse noisy whitespace while preserving paragraph breaks."""

    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _strip_repeated_margin_lines(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove repeated header/footer lines that commonly pollute PDF extraction."""

    if len(pages) < 2:
        return pages

    first_line_counter: Counter[str] = Counter()
    last_line_counter: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page["text"].splitlines() if line.strip()]
        if lines:
            first_line_counter[lines[0]] += 1
            last_line_counter[lines[-1]] += 1

    repeated_headers = {
        line for line, count in first_line_counter.items() if count >= 2 and len(line) >= 4
    }
    repeated_footers = {
        line for line, count in last_line_counter.items() if count >= 2 and len(line) >= 2
    }

    cleaned_pages: list[dict[str, Any]] = []
    for page in pages:
        lines = [line.strip() for line in page["text"].splitlines() if line.strip()]
        if lines and lines[0] in repeated_headers:
            lines = lines[1:]
        if lines and lines[-1] in repeated_footers:
            lines = lines[:-1]

        cleaned_pages.append(
            {
                "page_number": page["page_number"],
                "text": "\n".join(lines).strip(),
            }
        )

    return cleaned_pages


def _extract_title(first_page_text: str, pdf_metadata: dict[str, Any]) -> str:
    """Prefer embedded PDF metadata and fall back to the first plausible text line."""

    metadata_title = str(pdf_metadata.get("title") or "").strip()
    if metadata_title:
        return metadata_title

    candidates = []
    for line in first_page_text.splitlines():
        cleaned = " ".join(line.split()).strip()
        if not cleaned:
            continue
        if len(cleaned) < 10 or len(cleaned) > 250:
            continue
        if "@" in cleaned:
            continue
        if cleaned.lower().startswith(("abstract", "keywords")):
            continue
        candidates.append(cleaned)
        if len(candidates) >= 8:
            break

    if not candidates:
        return "Untitled Document"

    return max(candidates, key=len)


def _extract_with_pymupdf(pdf_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract page text and PDF metadata with PyMuPDF."""

    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("PyMuPDF is not installed. Install 'pymupdf' for PDF parsing.") from exc

    pages: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as pdf_document:
        pdf_metadata = dict(pdf_document.metadata or {})
        for index, page in enumerate(pdf_document, start=1):
            text = page.get_text("text", sort=True)
            pages.append({"page_number": index, "text": _normalize_whitespace(text)})

    return pages, pdf_metadata


def _extract_with_pdfplumber(pdf_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Extract page text with pdfplumber as a fallback parser."""

    try:
        import pdfplumber
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "No PDF parser is installed. Install 'pymupdf' or 'pdfplumber'."
        ) from exc

    pages: list[dict[str, Any]] = []
    with pdfplumber.open(pdf_path) as pdf_document:
        metadata = dict(pdf_document.metadata or {})
        for index, page in enumerate(pdf_document.pages, start=1):
            text = page.extract_text() or ""
            pages.append({"page_number": index, "text": _normalize_whitespace(text)})

    return pages, metadata


def parse_pdf(file_url: str) -> dict[str, Any]:
    """Parse a PDF file into title, metadata, page text, and full text."""

    pdf_path = _resolve_pdf_path(file_url)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        pages, pdf_metadata = _extract_with_pymupdf(pdf_path)
        parser_name = "pymupdf"
    except ModuleNotFoundError:
        pages, pdf_metadata = _extract_with_pdfplumber(pdf_path)
        parser_name = "pdfplumber"

    cleaned_pages = _strip_repeated_margin_lines(pages)
    nonempty_pages = [page for page in cleaned_pages if page["text"]]
    first_page_text = nonempty_pages[0]["text"] if nonempty_pages else ""
    title = _extract_title(first_page_text, pdf_metadata)
    full_text = "\n\n".join(page["text"] for page in nonempty_pages).strip()

    metadata_json = {
        "page_count": len(cleaned_pages),
        "parser": parser_name,
        "source_file": pdf_path.name,
        "authors": pdf_metadata.get("author"),
        "subject": pdf_metadata.get("subject"),
        "keywords": pdf_metadata.get("keywords"),
        "pdf_metadata": {key: value for key, value in pdf_metadata.items() if value},
    }

    return {
        "title": title,
        "metadata_json": metadata_json,
        "pages": cleaned_pages,
        "full_text": full_text,
    }
