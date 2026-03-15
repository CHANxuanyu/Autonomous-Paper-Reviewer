"""Multimodal PDF parsing utilities powered by Unstructured."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VISUAL_CATEGORIES = {"Image", "Table"}


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


def _extract_pdf_metadata(pdf_path: Path) -> tuple[dict[str, Any], int | None]:
    """Read lightweight PDF metadata separately from the Unstructured partition output."""

    try:
        import fitz
    except ModuleNotFoundError:
        return {}, None

    with fitz.open(pdf_path) as pdf_document:
        return dict(pdf_document.metadata or {}), len(pdf_document)


def _build_document_image_dir(document_id: Any | None, pdf_path: Path) -> Path:
    """Create a clean image extraction directory for the current document."""

    document_key = str(document_id or pdf_path.stem)
    images_dir = PROJECT_ROOT / "media" / "documents" / document_key / "images"
    if images_dir.exists():
        shutil.rmtree(images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


def _relative_to_project_root(path: Path) -> str:
    """Store project-relative media paths for portability in local development."""

    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _partition_with_unstructured(pdf_path: Path, images_dir: Path) -> list[Any]:
    """Run the Unstructured hi-res PDF partitioner with image/table extraction enabled."""

    try:
        from unstructured.partition.pdf import partition_pdf
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Unstructured PDF parsing is not installed. Install 'unstructured[pdf]' and the "
            "system packages 'poppler-utils', 'tesseract-ocr', and 'libmagic1'."
        ) from exc

    try:
        return partition_pdf(
            filename=str(pdf_path),
            strategy="hi_res",
            infer_table_structure=True,
            extract_image_block_types=["Image", "Table"],
            extract_image_block_output_dir=str(images_dir),
        )
    except Exception as exc:
        raise RuntimeError(
            "Unstructured failed to partition the PDF. Ensure 'unstructured[pdf]' is installed "
            "and the local OCR/image dependencies are available. "
            f"Original error: {exc}"
        ) from exc


def _normalize_visual_asset(
    raw_image_path: str | None,
    *,
    category: str,
    page_number: int | None,
    images_dir: Path,
    figure_count: int,
    table_count: int,
) -> str | None:
    """Convert extracted image assets into stable PNG files under the media directory."""

    if not raw_image_path:
        return None

    source_path = Path(raw_image_path)
    if not source_path.exists():
        return None

    try:
        from PIL import Image
    except ModuleNotFoundError:
        return _relative_to_project_root(source_path)

    label = "figure" if category == "Image" else "table"
    sequence = figure_count if label == "figure" else table_count
    page_suffix = f"_p{page_number}" if page_number is not None else ""
    target_path = images_dir / f"{label}_{sequence}{page_suffix}.png"

    with Image.open(source_path) as image:
        converted = image.convert("RGB") if image.mode != "RGB" else image.copy()
        converted.save(target_path, format="PNG")

    if source_path.resolve() != target_path.resolve():
        source_path.unlink(missing_ok=True)

    return _relative_to_project_root(target_path)


def parse_pdf(file_url: str, *, document_id: Any | None = None) -> dict[str, Any]:
    """Parse a PDF into text pages plus extracted figures/tables saved to disk."""

    pdf_path = _resolve_pdf_path(file_url)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    pdf_metadata, pdf_page_count = _extract_pdf_metadata(pdf_path)
    images_dir = _build_document_image_dir(document_id, pdf_path)
    elements = _partition_with_unstructured(pdf_path, images_dir)

    pages_by_number: dict[int, dict[str, Any]] = {}
    figure_count = 0
    table_count = 0

    for order, element in enumerate(elements):
        metadata = getattr(element, "metadata", None)
        page_number = getattr(metadata, "page_number", None) or 1
        category = str(getattr(element, "category", type(element).__name__) or type(element).__name__)
        page_entry = pages_by_number.setdefault(
            page_number,
            {
                "page_number": page_number,
                "text_blocks": [],
                "visual_blocks": [],
            },
        )

        text = _normalize_whitespace(str(getattr(element, "text", "") or ""))
        if category in VISUAL_CATEGORIES:
            if category == "Image":
                figure_count += 1
            else:
                table_count += 1

            image_path = _normalize_visual_asset(
                getattr(metadata, "image_path", None),
                category=category,
                page_number=page_number,
                images_dir=images_dir,
                figure_count=figure_count,
                table_count=table_count,
            )
            preceding_text_order = (
                page_entry["text_blocks"][-1]["order"] if page_entry["text_blocks"] else None
            )
            page_entry["visual_blocks"].append(
                {
                    "order": order,
                    "category": category,
                    "image_path": image_path,
                    "caption_or_context": text or None,
                    "anchor_text_order": preceding_text_order,
                }
            )
            continue

        if category == "PageBreak" or not text:
            continue

        page_entry["text_blocks"].append(
            {
                "order": order,
                "category": category,
                "text": text,
            }
        )

    visual_blocks: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    for page_number in sorted(pages_by_number):
        page_entry = pages_by_number[page_number]
        text_blocks = page_entry["text_blocks"]
        order_to_text = {block["order"]: block["text"] for block in text_blocks}
        text_orders = [block["order"] for block in text_blocks]

        for visual_block in page_entry["visual_blocks"]:
            if visual_block["anchor_text_order"] is None:
                visual_block["anchor_text_order"] = next(
                    (order for order in text_orders if order > visual_block["order"]),
                    None,
                )
            if not visual_block.get("caption_or_context") and visual_block["anchor_text_order"] is not None:
                visual_block["caption_or_context"] = order_to_text.get(visual_block["anchor_text_order"])
            visual_blocks.append(visual_block)

        page_text = "\n\n".join(block["text"] for block in text_blocks).strip()
        pages.append(
            {
                "page_number": page_number,
                "text": page_text,
                "text_blocks": text_blocks,
                "visual_blocks": page_entry["visual_blocks"],
            }
        )

    first_page_text = next((page["text"] for page in pages if page["text"]), "")
    title = _extract_title(first_page_text, pdf_metadata)
    full_text = "\n\n".join(page["text"] for page in pages if page["text"]).strip()

    metadata_json = {
        "page_count": pdf_page_count or len(pages),
        "parser": "unstructured_hi_res",
        "source_file": pdf_path.name,
        "authors": pdf_metadata.get("author"),
        "subject": pdf_metadata.get("subject"),
        "keywords": pdf_metadata.get("keywords"),
        "figure_count": figure_count,
        "table_count": table_count,
        "visual_asset_count": len([block for block in visual_blocks if block.get("image_path")]),
        "media_dir": _relative_to_project_root(images_dir),
        "pdf_metadata": {key: value for key, value in pdf_metadata.items() if value},
    }

    return {
        "title": title,
        "metadata_json": metadata_json,
        "pages": pages,
        "full_text": full_text,
        "visual_blocks": visual_blocks,
    }
