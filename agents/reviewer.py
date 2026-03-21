"""Reviewer agent for generating the final structured peer-review report."""

from __future__ import annotations

import base64
import json
import os
import re
from textwrap import shorten
from typing import Any

from agents import claim_verifier
from agents.tool_client import execute_mcp_tool_sync
from schemas.review import (
    ClaimVerificationRunSummarySchema,
    ClaimVerificationSchema,
    ExternalReferenceSchema,
    ReviewResultSchema,
)

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
        chunk_text = " ".join(str(evidence.get("chunk_text") or "").split())
        compacted.append(
            {
                "claim": evidence.get("claim"),
                "query_text": evidence.get("query_text"),
                "chunk_id": str(evidence.get("chunk_id")) if evidence.get("chunk_id") else None,
                "confidence_score": evidence.get("confidence_score"),
                "score": evidence.get("score"),
                "evidence_type": evidence.get("evidence_type"),
                "page_number": evidence.get("page_number"),
                "section_name": evidence.get("section_name"),
                "chunk_index": evidence.get("chunk_index"),
                "linked_image_path": evidence.get("linked_image_path"),
                "vector_distance": evidence.get("vector_distance"),
                "keyword_overlap": evidence.get("keyword_overlap"),
                "retrieval_rank": evidence.get("retrieval_rank"),
                "chunk_text": shorten(chunk_text, width=700, placeholder="...") if chunk_text else "",
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
    claim_verifications: list[dict[str, Any]],
    claim_verification_summary: dict[str, Any] | None,
) -> str:
    """Build the shared review payload used for both planning and final generation."""

    return (
        f"Paper title:\n{title}\n\n"
        f"Paper metadata:\n{_json_dump(metadata_json)}\n\n"
        f"Abstract or first-page excerpt:\n{abstract_or_excerpt}\n\n"
        f"Review plan:\n{_json_dump(review_plan)}\n\n"
        f"Retrieved evidences:\n{_json_dump(compacted_evidences)}\n\n"
        f"Claim verification results:\n{_json_dump(claim_verifications)}\n\n"
        f"Claim verification summary:\n{_json_dump(claim_verification_summary)}\n\n"
        "Generate a concise academic review report. "
        "Summary should be 2 to 4 sentences. "
        "Strengths and weaknesses should each contain concrete, reviewer-style points. "
        "Use missing_evidence for claims that could not be sufficiently verified. "
        "Use questions_for_authors for follow-up questions that would materially affect confidence. "
        "Use code_reproducibility_check to summarize the health of any claimed public code repository, "
        "or to note gracefully when the GitHub tool could not verify it. "
        "The claim_verifications field should preserve the dedicated claim verification stage outputs already provided. "
        "If those claim_verifications already include external checks, prefer using them before deciding to call more tools. "
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
        try:
            payload = json.loads(raw_output)
        except Exception:
            payload = None

        if isinstance(payload, dict):
            tool_name = str(payload.get("tool") or "")
            results = payload.get("results") if isinstance(payload.get("results"), list) else []
            for result in results:
                if not isinstance(result, dict):
                    continue
                title = _clean_tool_text(str(result.get("title") or ""))
                if not title:
                    continue

                title_key = title.casefold()
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)

                references.append(
                    ExternalReferenceSchema(
                        title=title,
                        authors=[str(author) for author in result.get("authors") or [] if str(author).strip()],
                        published_date=(
                            _clean_tool_text(str(result.get("published_date") or ""))
                            if tool_name == "search_arxiv"
                            else None
                        )
                        or None,
                        summary=_clean_tool_text(str(result.get("summary") or "")) or None,
                        citation_count=(
                            int(result.get("citation_count"))
                            if result.get("citation_count") is not None
                            else None
                        ),
                        influential_citation_count=(
                            int(result.get("influential_citation_count"))
                            if result.get("influential_citation_count") is not None
                            else None
                        ),
                    ).model_dump()
                )
            if results:
                continue

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


def _semantic_scholar_tool_definition() -> dict[str, Any]:
    """Describe the Semantic Scholar academic graph tool to the model."""

    return {
        "type": "function",
        "name": "search_semantic_scholar",
        "description": (
            "Search the broader Semantic Scholar academic graph across all domains to "
            "find related papers, citation counts, and influential papers beyond ArXiv."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A citation-oriented or related-work query derived from the paper.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many Semantic Scholar matches to return.",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                },
            },
            "required": ["query", "limit"],
            "additionalProperties": False,
        },
    }


def _github_check_tool_definition() -> dict[str, Any]:
    """Describe the local GitHub repository verification tool to the model."""

    return {
        "type": "function",
        "name": "check_github_repo",
        "description": (
            "Check whether a GitHub repository mentioned in the paper is real, reachable, "
            "and plausibly maintained for code reproducibility assessment."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "The GitHub repository URL claimed by the paper authors.",
                }
            },
            "required": ["repo_url"],
            "additionalProperties": False,
        },
    }


def _execute_python_code_tool_definition() -> dict[str, Any]:
    """Describe the local Python code sandbox tool to the model."""

    return {
        "type": "function",
        "name": "execute_python_code",
        "description": (
            "Write and execute Python code in an isolated sandbox to verify mathematical "
            "formulas, statistics, or algorithm logic mentioned in the paper. You must "
            "explicitly print() the results you want to see."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to run. Use print() for any outputs you want returned.",
                }
            },
            "required": ["code"],
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
        "- Use search_arxiv when you want recent preprints, novelty checks, or emerging related work that is commonly discussed on ArXiv.\n"
        "- Use search_semantic_scholar when you need broader academic coverage, citation counts, influential papers, or stronger signals about the established literature.\n"
        "- If the authors claim their code is publicly available and provide a GitHub URL, you MUST extract that URL and use the check_github_repo tool.\n"
        "- If you need to verify mathematical equations, statistics, or logic, use the execute_python_code tool to run a Python script. Remember to print the output.\n"
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
            tools=[
                _arxiv_search_tool_definition(),
                _semantic_scholar_tool_definition(),
                _github_check_tool_definition(),
                _execute_python_code_tool_definition(),
            ],
            parallel_tool_calls=False,
            max_tool_calls=4,
            temperature=0.2,
            max_output_tokens=700,
        )
    except Exception as exc:
        raise RuntimeError(f"Reviewer reasoning phase failed: {exc}") from exc

    tool_outputs: list[dict[str, str]] = []
    for item in initial_response.output:
        if getattr(item, "type", None) != "function_call":
            continue
        function_name = getattr(item, "name", None)
        if function_name not in {
            "search_arxiv",
            "search_semantic_scholar",
            "check_github_repo",
            "execute_python_code",
        }:
            continue

        try:
            arguments = json.loads(item.arguments or "{}")
        except json.JSONDecodeError as exc:
            tool_result = f"Tool arguments were invalid JSON for {function_name}: {exc}"
        else:
            tool_result = execute_mcp_tool_sync(function_name, arguments)

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
    *,
    claim_verifications: list[dict[str, Any]] | None = None,
    claim_verification_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate the final structured peer-review result."""

    client = _get_openai_client()

    title = str(parsed_document.get("title") or "Untitled Document")
    metadata_json = parsed_document.get("metadata_json") or {}
    abstract_or_excerpt = _extract_abstract(parsed_document)
    compacted_evidences = _compact_evidences(evidences)
    claim_verifications = list(
        claim_verifications
        or claim_verifier.build_claim_verification_scaffold(
            review_plan,
            evidences,
            parsed_document=parsed_document,
        )
    )

    system_prompt = (
        "You are a careful academic reviewer. "
        "Write a balanced peer-review style assessment grounded in the supplied evidence. "
        "Do not invent experimental details that are not supported by the inputs. "
        "If evidence is weak, say so in missing_evidence or questions_for_authors rather than overstating certainty. "
        "Treat claim_verifications as an authoritative audit artifact produced by a dedicated verification stage. "
        "Use them to inform the review, but do not invent new claims or delete the existing verification lineage. "
        "If a claim_verification already includes external checks, treat that as the primary external-verification record for that claim. "
        "Use search_arxiv for recent preprints, novelty checks, and emerging related work. "
        "Use search_semantic_scholar when you need broader literature coverage, citation counts, or influential-paper signals. "
        "When you add Semantic Scholar references to external_references_checked, populate citation_count and influential_citation_count whenever those values are available. "
        "If the authors claim their code is publicly available and provide a GitHub URL, you MUST extract that URL and use the check_github_repo tool. "
        "If you need to verify mathematical equations, statistics, or algorithm logic, you MUST use the execute_python_code tool and explicitly print the outputs you want to inspect. "
        "If the tool fails, gracefully mention the failure in your final review. "
        "Return only the structured review result."
    )

    user_prompt = _build_review_prompt(
        title=title,
        metadata_json=metadata_json,
        abstract_or_excerpt=abstract_or_excerpt,
        review_plan=review_plan,
        compacted_evidences=compacted_evidences,
        claim_verifications=claim_verifications,
        claim_verification_summary=claim_verification_summary,
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

    report_payload = report.model_dump(mode="json")
    report_payload["claim_verifications"] = [
        ClaimVerificationSchema.model_validate(verification).model_dump(mode="json")
        for verification in claim_verifications
    ]
    report_payload["claim_verification_summary"] = (
        ClaimVerificationRunSummarySchema.model_validate(claim_verification_summary).model_dump(mode="json")
        if claim_verification_summary
        else None
    )
    report_payload["external_references_checked"] = _extract_external_references(tool_outputs)
    return report_payload
