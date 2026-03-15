"""Reviewer agent for generating the final structured peer-review report."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from schemas.review import ReviewResultSchema

REVIEW_MODEL = os.getenv("OPENAI_REVIEW_MODEL", "gpt-4o-mini")
REVIEW_TIMEOUT_SECONDS = float(os.getenv("OPENAI_REVIEW_TIMEOUT_SECONDS", "90"))

ABSTRACT_PATTERN = re.compile(
    r"abstract[\s:]*?(.*?)(?:\n\s*(?:1\.?\s+)?introduction\b|\n\s*keywords\b|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _get_openai_client():
    """Create an OpenAI client lazily so import-time stays lightweight."""

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("The 'openai' package is required for the reviewer agent.") from exc

    return OpenAI(timeout=REVIEW_TIMEOUT_SECONDS, max_retries=2)


def _extract_abstract(parsed_document: dict[str, Any]) -> str:
    """Extract an abstract-like snippet from the parsed paper text."""

    full_text = str(parsed_document.get("full_text") or "")
    if full_text:
        match = ABSTRACT_PATTERN.search(full_text)
        if match:
            abstract = " ".join(match.group(1).split())
            if abstract:
                return abstract[:3000]

    pages = parsed_document.get("pages") or []
    if pages:
        return str(pages[0].get("text") or "")[:3000]

    return ""


def _compact_evidences(evidences: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    """Trim evidence payload size before sending it to the LLM."""

    compacted: list[dict[str, Any]] = []
    for evidence in evidences[:limit]:
        compacted.append(
            {
                "claim": evidence.get("claim"),
                "chunk_id": str(evidence.get("chunk_id")) if evidence.get("chunk_id") else None,
                "confidence_score": evidence.get("confidence_score"),
                "evidence_type": evidence.get("evidence_type"),
            }
        )
    return compacted


def generate_report(
    parsed_document: dict[str, Any],
    review_plan: dict[str, Any],
    evidences: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate the final structured peer-review result."""

    client = _get_openai_client()

    title = str(parsed_document.get("title") or "Untitled Document")
    metadata_json = parsed_document.get("metadata_json") or {}
    abstract_or_excerpt = _extract_abstract(parsed_document)
    compacted_evidences = _compact_evidences(evidences)

    system_prompt = (
        "You are a careful academic reviewer. "
        "Write a balanced peer-review style assessment grounded in the supplied evidence. "
        "Do not invent experimental details that are not supported by the inputs. "
        "If evidence is weak, say so in missing_evidence or questions_for_authors rather than overstating certainty. "
        "Return only the structured review result."
    )

    user_prompt = (
        f"Paper title:\n{title}\n\n"
        f"Paper metadata:\n{json.dumps(metadata_json, ensure_ascii=False)}\n\n"
        f"Abstract or first-page excerpt:\n{abstract_or_excerpt}\n\n"
        f"Review plan:\n{json.dumps(review_plan, ensure_ascii=False)}\n\n"
        f"Retrieved evidences:\n{json.dumps(compacted_evidences, ensure_ascii=False)}\n\n"
        "Generate a concise academic review report. "
        "Summary should be 2 to 4 sentences. "
        "Strengths and weaknesses should each contain concrete, reviewer-style points. "
        "Use missing_evidence for claims that could not be sufficiently verified. "
        "Use questions_for_authors for follow-up questions that would materially affect confidence."
    )

    try:
        response = client.responses.parse(
            model=REVIEW_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=ReviewResultSchema,
            temperature=0.2,
            max_output_tokens=1600,
        )
    except Exception as exc:
        raise RuntimeError(f"Reviewer report generation failed: {exc}") from exc

    report = response.output_parsed
    if report is None:
        raise RuntimeError("Reviewer returned no structured report.")

    return report.model_dump()
