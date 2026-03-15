"""Reviewer agent for generating the final structured peer-review report."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

from schemas.review import ExternalReferenceSchema, ReviewResultSchema
from tools.arxiv_search import search_arxiv

REVIEW_MODEL = os.getenv("OPENAI_REVIEW_MODEL", "gpt-4o-mini")
REVIEW_TIMEOUT_SECONDS = float(os.getenv("OPENAI_REVIEW_TIMEOUT_SECONDS", "90"))

ABSTRACT_PATTERN = re.compile(
    r"abstract[\s:]*?(.*?)(?:\n\s*(?:1\.?\s+)?introduction\b|\n\s*keywords\b|\Z)",
    re.IGNORECASE | re.DOTALL,
)
ARXIV_RESULT_PATTERN = re.compile(
    r"(?ms)^\d+\.\s+Title:\s*(?P<title>.+?)\n"
    r"\s*Authors:\s*(?P<authors>.+?)\n"
    r"\s*Published:\s*(?P<published>.+?)\n"
    r"\s*Summary:\s*(?P<summary>.+?)(?=\n\d+\.\s+Title:|\Z)"
)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_openai_client():
    """Create an OpenAI client lazily so import-time stays lightweight."""

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("The 'openai' package is required for the reviewer agent.") from exc

    return OpenAI(timeout=REVIEW_TIMEOUT_SECONDS, max_retries=2)


def _review_model_name() -> str:
    """Force the reviewer onto a vision-capable GPT-4o family model."""

    if REVIEW_MODEL.startswith("gpt-4o"):
        return REVIEW_MODEL
    return "gpt-4o-mini"


def _encode_image(image_path: str) -> str:
    """Read a local image file and return its base64-encoded payload."""

    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


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


def _json_dump(payload: Any) -> str:
    """Serialize prompt payloads safely for the LLM context window."""

    return json.dumps(payload, ensure_ascii=False, default=str)


def _build_review_prompt(
    *,
    title: str,
    metadata_json: dict[str, Any],
    abstract_or_excerpt: str,
    review_plan: dict[str, Any],
    compacted_evidences: list[dict[str, Any]],
) -> str:
    """Build the shared review payload used for both planning and final generation."""

    return (
        f"Paper title:\n{title}\n\n"
        f"Paper metadata:\n{_json_dump(metadata_json)}\n\n"
        f"Abstract or first-page excerpt:\n{abstract_or_excerpt}\n\n"
        f"Review plan:\n{_json_dump(review_plan)}\n\n"
        f"Retrieved evidences:\n{_json_dump(compacted_evidences)}\n\n"
        "Generate a concise academic review report. "
        "Summary should be 2 to 4 sentences. "
        "Strengths and weaknesses should each contain concrete, reviewer-style points. "
        "Use missing_evidence for claims that could not be sufficiently verified. "
        "Use questions_for_authors for follow-up questions that would materially affect confidence. "
        "If external references are supplied later, incorporate them into the novelty and related-work assessment."
    )


def _resolve_image_path(image_path: str | None) -> str | None:
    """Resolve a stored image path into a readable local file path."""

    if not image_path:
        return None
    if os.path.isabs(image_path):
        return image_path
    return os.path.join(PROJECT_ROOT, image_path)


def _guess_image_mime_type(image_path: str) -> str:
    """Infer a reasonable data-URL MIME type from the file extension."""

    _, extension = os.path.splitext(image_path.lower())
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".webp":
        return "image/webp"
    return "image/png"


def _build_multimodal_user_content(
    *,
    text_payload: str,
    evidences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Construct a multimodal Responses API content array with text plus extracted figures."""

    content: list[dict[str, Any]] = [{"type": "input_text", "text": text_payload}]
    seen_paths: set[str] = set()

    for evidence in evidences:
        resolved_path = _resolve_image_path(str(evidence.get("linked_image_path") or "").strip() or None)
        if not resolved_path or not os.path.exists(resolved_path):
            continue
        if resolved_path in seen_paths:
            continue
        seen_paths.add(resolved_path)

        encoded_image = _encode_image(resolved_path)
        mime_type = _guess_image_mime_type(resolved_path)
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{encoded_image}",
            }
        )

    return content


def _clean_tool_text(value: str | None) -> str:
    """Normalize multiline tool output fields into a compact single line."""

    return " ".join((value or "").split())


def _extract_external_references(tool_outputs: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse ArXiv tool output into structured references for persistence and UI rendering."""

    references: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for tool_output in tool_outputs:
        raw_output = str(tool_output.get("output") or "")
        for match in ARXIV_RESULT_PATTERN.finditer(raw_output):
            title = _clean_tool_text(match.group("title"))
            if not title:
                continue

            title_key = title.casefold()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            authors = [
                author.strip()
                for author in _clean_tool_text(match.group("authors")).split(",")
                if author.strip() and author.strip().lower() != "unknown authors"
            ]
            published_date = _clean_tool_text(match.group("published"))
            summary = _clean_tool_text(match.group("summary"))

            references.append(
                ExternalReferenceSchema(
                    title=title,
                    authors=authors,
                    published_date=None if published_date == "Unknown" else published_date,
                    summary=None if summary == "No summary available." else summary,
                ).model_dump()
            )

    return references


def _arxiv_search_tool_definition() -> dict[str, Any]:
    """Describe the local ArXiv tool to the model."""

    return {
        "type": "function",
        "name": "search_arxiv",
        "description": (
            "Search the ArXiv database to verify novelty, find related work, "
            "or check if the paper's claims are truly original."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A short related-work or novelty-check query derived from the paper.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "How many ArXiv matches to return.",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                },
            },
            "required": ["query", "max_results"],
            "additionalProperties": False,
        },
    }


def _run_reasoning_and_tools(
    client: Any,
    *,
    system_prompt: str,
    review_prompt: str,
    evidences: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, str]]]:
    """Let the model decide whether external ArXiv verification is needed."""

    planning_prompt = (
        f"{review_prompt}\n\n"
        "Reasoning & tool execution phase:\n"
        "- First decide whether external novelty verification or related-work lookup is needed.\n"
        "- If ArXiv context would materially improve the review, call search_arxiv.\n"
        "- If the provided paper evidence is enough, do not call any tool.\n"
        "- Do not produce the final structured review yet."
    )

    try:
        initial_response = client.responses.create(
            model=_review_model_name(),
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": _build_multimodal_user_content(
                        text_payload=planning_prompt,
                        evidences=evidences,
                    ),
                },
            ],
            tools=[_arxiv_search_tool_definition()],
            parallel_tool_calls=False,
            max_tool_calls=1,
            temperature=0.2,
            max_output_tokens=700,
        )
    except Exception as exc:
        raise RuntimeError(f"Reviewer reasoning phase failed: {exc}") from exc

    tool_outputs: list[dict[str, str]] = []
    for item in initial_response.output:
        if getattr(item, "type", None) != "function_call" or getattr(item, "name", None) != "search_arxiv":
            continue

        try:
            arguments = json.loads(item.arguments or "{}")
        except json.JSONDecodeError as exc:
            tool_result = f"ArXiv tool arguments were invalid JSON: {exc}"
        else:
            query = str(arguments.get("query") or "").strip()
            try:
                max_results = int(arguments.get("max_results", 3))
            except (TypeError, ValueError):
                max_results = 3
            tool_result = search_arxiv(query=query, max_results=max_results)

        tool_outputs.append(
            {
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": tool_result,
            }
        )

    return initial_response.id, tool_outputs


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

    user_prompt = _build_review_prompt(
        title=title,
        metadata_json=metadata_json,
        abstract_or_excerpt=abstract_or_excerpt,
        review_plan=review_plan,
        compacted_evidences=compacted_evidences,
    )

    try:
        previous_response_id, tool_outputs = _run_reasoning_and_tools(
            client,
            system_prompt=system_prompt,
            review_prompt=user_prompt,
            evidences=evidences,
        )

        final_instruction = (
            "Use the ArXiv tool findings together with the PDF evidence and produce the final structured review now."
            if tool_outputs
            else "No external tool use was needed. Produce the final structured review now using the paper evidence already provided."
        )
        final_input: list[dict[str, Any]]
        if tool_outputs:
            final_input = tool_outputs + [
                {
                    "role": "user",
                    "content": _build_multimodal_user_content(
                        text_payload=f"{user_prompt}\n\nFinal review phase:\n{final_instruction}",
                        evidences=evidences,
                    ),
                }
            ]
        else:
            final_input = [
                {
                    "role": "user",
                    "content": _build_multimodal_user_content(
                        text_payload=f"{user_prompt}\n\nFinal review phase:\n{final_instruction}",
                        evidences=evidences,
                    ),
                }
            ]

        response = client.responses.parse(
            model=_review_model_name(),
            previous_response_id=previous_response_id,
            input=final_input,
            text_format=ReviewResultSchema,
            temperature=0.2,
            max_output_tokens=1600,
        )
    except Exception as exc:
        raise RuntimeError(f"Reviewer report generation failed: {exc}") from exc

    report = response.output_parsed
    if report is None:
        raise RuntimeError("Reviewer returned no structured report.")

    report_payload = report.model_dump()
    report_payload["external_references_checked"] = _extract_external_references(tool_outputs)
    return report_payload
