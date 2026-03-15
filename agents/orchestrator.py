"""Orchestrator agent for planning paper review evidence retrieval."""

from __future__ import annotations

import os
import re
from typing import Any

from pydantic import BaseModel, Field

PLANNING_MODEL = os.getenv("OPENAI_PLANNING_MODEL", "gpt-4o-mini")
PLANNING_TIMEOUT_SECONDS = float(os.getenv("OPENAI_PLANNING_TIMEOUT_SECONDS", "60"))

ABSTRACT_PATTERN = re.compile(
    r"abstract[\s:]*?(.*?)(?:\n\s*(?:1\.?\s+)?introduction\b|\n\s*keywords\b|\Z)",
    re.IGNORECASE | re.DOTALL,
)


class ReviewPlanItem(BaseModel):
    """One retrieval-oriented review question or claim."""

    aspect: str = Field(description="Review dimension such as methodology or experiments.")
    claim: str = Field(description="Specific retrieval question or verification target.")
    rationale: str = Field(description="Why this item matters for academic review quality.")
    search_keywords: list[str] = Field(
        default_factory=list,
        description="Optional keywords to improve evidence retrieval coverage.",
    )
    priority: int = Field(ge=1, le=5, description="Relative importance, where 1 is highest priority.")


class ReviewPlanSchema(BaseModel):
    """Structured retrieval plan produced by the orchestrator."""

    plan_summary: str = Field(description="Short summary of the intended review strategy.")
    focus_areas: list[str] = Field(default_factory=list, description="User-requested focus areas.")
    queries: list[ReviewPlanItem] = Field(
        default_factory=list,
        description="Concrete retrieval tasks for the evidence retriever.",
    )


def _get_openai_client():
    """Create an OpenAI client lazily so import-time stays lightweight."""

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("The 'openai' package is required for the orchestrator agent.") from exc

    return OpenAI(timeout=PLANNING_TIMEOUT_SECONDS, max_retries=2)


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
        first_page_text = str(pages[0].get("text") or "")
        return first_page_text[:3000]

    return ""


def plan_review(focus_areas: list[str], parsed_document: dict[str, Any]) -> dict[str, Any]:
    """Create a structured evidence-retrieval plan for academic review."""

    client = _get_openai_client()

    title = str(parsed_document.get("title") or "Untitled Document")
    abstract_or_excerpt = _extract_abstract(parsed_document)
    metadata_json = parsed_document.get("metadata_json") or {}

    system_prompt = (
        "You are a senior academic peer-review orchestrator. "
        "Produce a concise, retrieval-oriented review plan for a research paper. "
        "Focus on evidence that can be verified from the paper text, such as methodology details, "
        "dataset scale, baseline comparisons, ablations, limitations, and claims of novelty. "
        "Return only the structured plan. Avoid speculative judgments."
    )

    user_prompt = (
        f"Paper title:\n{title}\n\n"
        f"User focus areas:\n{focus_areas or ['general_quality']}\n\n"
        f"Paper metadata:\n{metadata_json}\n\n"
        f"Abstract or first-page excerpt:\n{abstract_or_excerpt}\n\n"
        "Create 5 to 10 high-value retrieval queries or claims for downstream evidence lookup. "
        "Each item should be specific enough that a vector retriever can search for supporting passages."
    )

    try:
        response = client.responses.parse(
            model=PLANNING_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=ReviewPlanSchema,
            temperature=0.2,
            max_output_tokens=1200,
        )
    except Exception as exc:
        raise RuntimeError(f"Orchestrator planning failed: {exc}") from exc

    plan = response.output_parsed
    if plan is None:
        raise RuntimeError("Orchestrator returned no structured review plan.")

    return plan.model_dump()
