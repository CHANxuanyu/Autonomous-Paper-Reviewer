"""Dedicated claim verification stage with selective external checks."""

from __future__ import annotations

import json
import os
import re
from collections import OrderedDict, defaultdict
from collections.abc import Callable, Sequence
from textwrap import shorten
from time import perf_counter
from typing import Any

import openai
from pydantic import BaseModel, ConfigDict, Field

from agents.external_evidence import normalize_external_tool_output, resolve_external_evidence
from agents.tool_client import execute_mcp_tool_sync
from rag import retriever
from schemas.enums import (
    ClaimSourceType,
    ClaimVerificationVerdict,
    ExternalCheckStatus,
    ExternalResolutionStatus,
    ExternalToolName,
)
from schemas.review import (
    ClaimExternalCheckSchema,
    ClaimVerificationRunSummarySchema,
    ClaimVerificationSchema,
)

CLAIM_VERIFIER_MODEL = os.getenv("OPENAI_CLAIM_VERIFIER_MODEL", "gpt-4o-mini")
CLAIM_VERIFIER_TIMEOUT_SECONDS = float(os.getenv("OPENAI_CLAIM_VERIFIER_TIMEOUT_SECONDS", "60"))
DEFAULT_MAX_CLAIMS = int(os.getenv("CLAIM_VERIFIER_MAX_CLAIMS", "8"))
MAX_EVIDENCES_PER_CLAIM = 4
MAX_EXTERNAL_TOOLS_PER_CLAIM = 2
CLAIM_RETRIEVAL_REFRESH_THRESHOLD = 0.52
MAX_EXTERNAL_SUMMARY_CHARS = 900
MAX_EXTERNAL_RAW_OUTPUT_CHARS = 1800

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
CLAIM_HINT_PATTERN = re.compile(
    r"\b("
    r"we propose|we present|we introduce|we show|we demonstrate|we find|we achieve|"
    r"outperform|state[- ]of[- ]the[- ]art|sota|novel|first\b|significant(?:ly)?|"
    r"publicly available|open[- ]source|github|reproducib"
    r")\b",
    re.IGNORECASE,
)
CODE_CHECK_PATTERN = re.compile(r"\b(code|github|open[- ]source|repository|reproducib)\b", re.IGNORECASE)
LITERATURE_CHECK_PATTERN = re.compile(
    r"\b("
    r"novel|novelty|original|first\b|state[- ]of[- ]the[- ]art|sota|best\b|"
    r"outperform(?:s|ed)?\b|superior to prior|prior work|related work|literature|"
    r"citation|influential|benchmark leader|baseline"
    r")\b",
    re.IGNORECASE,
)
NOVELTY_CHECK_PATTERN = re.compile(
    r"\b(novel|novelty|original|first\b|state[- ]of[- ]the[- ]art|sota|unprecedented)\b",
    re.IGNORECASE,
)
GITHUB_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?(?:/|$)",
    re.IGNORECASE,
)

EXTERNAL_CHECK_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(novel|novelty|original|first\b|unprecedented)\b", re.IGNORECASE),
        "This claim depends on novelty or originality relative to external literature.",
    ),
    (
        re.compile(r"\b(state[- ]of[- ]the[- ]art|sota|best\b|outperform(?:s|ed)?\b|superior to prior)\b", re.IGNORECASE),
        "This claim depends on broad comparison against prior work beyond the paper's internal evidence.",
    ),
    (
        re.compile(r"\b(citation|related work|prior work|literature|benchmark leader)\b", re.IGNORECASE),
        "This claim depends on external literature coverage or citation context.",
    ),
    (
        re.compile(r"\b(code|github|open[- ]source|repository|reproducib)\b", re.IGNORECASE),
        "This claim depends on external repository or reproducibility checks.",
    ),
)


class ClaimCandidateSchema(BaseModel):
    """Internal claim candidate representation used by the verification stage."""

    model_config = ConfigDict(from_attributes=True)

    claim_text: str
    claim_source: ClaimSourceType
    aspect: str | None = None
    priority: int | None = None
    search_keywords: list[str] = Field(default_factory=list)


class InternalClaimAssessmentSchema(BaseModel):
    """Structured internal-only claim assessment before external tools run."""

    model_config = ConfigDict(from_attributes=True)

    verdict: ClaimVerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    needs_external_check: bool = False
    external_check_reason: str | None = None
    notes: str | None = None


class ExternalToolRequestSchema(BaseModel):
    """Internal deterministic tool-selection payload for one flagged claim."""

    model_config = ConfigDict(from_attributes=True)

    tool_name: ExternalToolName
    rationale: str
    request_payload: dict[str, Any] = Field(default_factory=dict)


def _get_openai_client():
    """Create an OpenAI client lazily so import-time stays lightweight."""

    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("The 'openai' package is required for claim verification.") from exc

    return OpenAI(timeout=CLAIM_VERIFIER_TIMEOUT_SECONDS, max_retries=2)


def _normalize_claim_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _clean_tool_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _abstract_or_excerpt(parsed_document: dict[str, Any], *, limit: int = 2400) -> str:
    """Extract a compact paper excerpt for claim verification prompts."""

    full_text = str(parsed_document.get("full_text") or "").strip()
    if full_text:
        return full_text[:limit]

    pages = parsed_document.get("pages") or []
    if pages:
        return str(pages[0].get("text") or "")[:limit]

    return ""


def _fallback_text_windows(parsed_document: dict[str, Any]) -> list[str]:
    """Collect small text windows for heuristic claim fallback extraction."""

    windows: list[str] = []
    excerpt = _abstract_or_excerpt(parsed_document, limit=2500)
    if excerpt:
        windows.append(excerpt)

    full_text = str(parsed_document.get("full_text") or "").strip()
    if full_text:
        windows.append(full_text[:2500])
        windows.append(full_text[-2000:])

    return windows


def _external_check_reason(claim_text: str) -> str | None:
    """Return a concrete reason when a claim likely requires external verification."""

    normalized_claim = _normalize_claim_text(claim_text)
    for pattern, reason in EXTERNAL_CHECK_RULES:
        if pattern.search(normalized_claim):
            return reason
    return None


def _evidence_sort_key(evidence: dict[str, Any]) -> tuple[float, float]:
    """Sort evidences by confidence first, then by lower retrieval rank."""

    confidence_score = float(evidence.get("confidence_score") or evidence.get("score") or 0.0)
    retrieval_rank = float(evidence.get("retrieval_rank") or 999.0)
    return (confidence_score, -retrieval_rank)


def _sorted_evidences(evidences: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return evidences sorted from strongest to weakest."""

    return sorted(evidences, key=_evidence_sort_key, reverse=True)


def _group_evidences_by_claim(evidences: Sequence[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group richer retrieval objects by normalized claim text."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evidence in evidences:
        claim_key = _normalize_claim_text(evidence.get("claim")).casefold()
        if not claim_key:
            continue
        grouped[claim_key].append(evidence)

    return {claim_key: _sorted_evidences(items) for claim_key, items in grouped.items()}


def _claim_plan_for_candidate(candidate: ClaimCandidateSchema, review_plan: dict[str, Any]) -> dict[str, Any]:
    """Build a single-claim retrieval plan for targeted evidence refresh."""

    return {
        "plan_summary": str(review_plan.get("plan_summary") or f"Claim verification plan for {candidate.claim_text}"),
        "focus_areas": list(review_plan.get("focus_areas") or []),
        "queries": [
            {
                "aspect": candidate.aspect or "claim_verification",
                "claim": candidate.claim_text,
                "rationale": "Targeted claim verification retrieval.",
                "search_keywords": list(candidate.search_keywords),
                "priority": candidate.priority or 1,
            }
        ],
    }


def _merge_evidence_sets(*evidence_sets: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate evidences while keeping the strongest record for each chunk/claim pair."""

    merged: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
    for evidence_set in evidence_sets:
        for evidence in evidence_set:
            evidence_key = (
                str(evidence.get("chunk_id") or ""),
                _normalize_claim_text(evidence.get("claim")).casefold(),
            )
            if not evidence_key[0] or not evidence_key[1]:
                continue
            existing = merged.get(evidence_key)
            if existing is None or _evidence_sort_key(evidence) > _evidence_sort_key(existing):
                merged[evidence_key] = evidence

    return _sorted_evidences(list(merged.values()))


def _evidence_lineage_payload(evidences: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Extract structured evidence lineage fields from retrieved evidences."""

    top_evidences = _sorted_evidences(evidences)[:MAX_EVIDENCES_PER_CLAIM]
    return {
        "evidence_chunk_ids": [
            str(evidence.get("chunk_id"))
            for evidence in top_evidences
            if evidence.get("chunk_id") is not None
        ],
        "evidence_quotes": [
            shorten(" ".join(str(evidence.get("chunk_text") or "").split()), width=320, placeholder="...")
            for evidence in top_evidences
            if str(evidence.get("chunk_text") or "").strip()
        ],
        "page_numbers": [
            int(page_number)
            for page_number in OrderedDict.fromkeys(
                evidence.get("page_number") for evidence in top_evidences if evidence.get("page_number") is not None
            )
        ],
        "section_names": [
            str(section_name)
            for section_name in OrderedDict.fromkeys(
                evidence.get("section_name") for evidence in top_evidences if evidence.get("section_name")
            )
        ],
        "linked_image_paths": [
            str(image_path)
            for image_path in OrderedDict.fromkeys(
                evidence.get("linked_image_path") for evidence in top_evidences if evidence.get("linked_image_path")
            )
        ],
    }


def _fallback_verdict(
    evidences: Sequence[dict[str, Any]],
    *,
    external_check_reason: str | None,
) -> ClaimVerificationVerdict:
    """Deterministic fallback verdict used when the verifier model is unavailable."""

    sorted_evidence = _sorted_evidences(evidences)
    if external_check_reason:
        top_score = 0.0
        if sorted_evidence:
            top_score = float(sorted_evidence[0].get("confidence_score") or sorted_evidence[0].get("score") or 0.0)
        if top_score < 0.7:
            return ClaimVerificationVerdict.NEEDS_EXTERNAL_VERIFICATION

    if not sorted_evidence:
        return ClaimVerificationVerdict.MISSING_EVIDENCE

    top_score = float(sorted_evidence[0].get("confidence_score") or sorted_evidence[0].get("score") or 0.0)
    if top_score >= 0.8:
        return ClaimVerificationVerdict.SUPPORTED
    if top_score >= 0.58:
        return ClaimVerificationVerdict.PARTIALLY_SUPPORTED
    return ClaimVerificationVerdict.MISSING_EVIDENCE


def _fallback_internal_note(
    verdict: ClaimVerificationVerdict,
    *,
    external_check_reason: str | None,
    error_message: str | None = None,
) -> str:
    """Build a concise deterministic note for internal fallback verifications."""

    if error_message:
        return (
            "Claim verifier fell back to deterministic scoring because model-based verification failed "
            f"({error_message})."
        )
    if verdict == ClaimVerificationVerdict.NEEDS_EXTERNAL_VERIFICATION and external_check_reason:
        return f"Internal evidence is insufficient for a final judgment. {external_check_reason}"
    if verdict == ClaimVerificationVerdict.SUPPORTED:
        return "Retrieved internal evidence strongly supports this claim."
    if verdict == ClaimVerificationVerdict.PARTIALLY_SUPPORTED:
        return "Retrieved internal evidence supports only part of the claim or leaves meaningful ambiguity."
    return "The paper does not provide enough internal evidence to support this claim confidently."


def _fallback_internal_assessment(
    evidences: Sequence[dict[str, Any]],
    *,
    external_check_reason: str | None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Create a deterministic internal claim assessment."""

    verdict = _fallback_verdict(evidences, external_check_reason=external_check_reason)
    confidence = 0.0
    sorted_evidence = _sorted_evidences(evidences)
    if sorted_evidence:
        confidence = round(float(sorted_evidence[0].get("confidence_score") or sorted_evidence[0].get("score") or 0.0), 2)

    return InternalClaimAssessmentSchema(
        verdict=verdict,
        confidence=confidence,
        needs_external_check=external_check_reason is not None or verdict == ClaimVerificationVerdict.NEEDS_EXTERNAL_VERIFICATION,
        external_check_reason=external_check_reason,
        notes=_fallback_internal_note(verdict, external_check_reason=external_check_reason, error_message=error_message),
    ).model_dump(mode="json")


def _candidate_from_dict(candidate: dict[str, Any]) -> ClaimCandidateSchema:
    """Validate a raw candidate payload."""

    return ClaimCandidateSchema.model_validate(candidate)


def _planner_claim_candidates(review_plan: dict[str, Any]) -> list[ClaimCandidateSchema]:
    """Extract claim candidates directly from planner queries when available."""

    raw_queries = review_plan.get("queries") or []
    candidates: list[ClaimCandidateSchema] = []
    for raw_query in raw_queries:
        if not isinstance(raw_query, dict):
            continue

        claim_text = _normalize_claim_text(
            raw_query.get("claim") or raw_query.get("query") or raw_query.get("question")
        )
        if not claim_text:
            continue

        search_keywords = [
            _normalize_claim_text(keyword)
            for keyword in (raw_query.get("search_keywords") or [])
            if _normalize_claim_text(keyword)
        ]

        priority: int | None = None
        try:
            raw_priority = raw_query.get("priority")
            if raw_priority is not None:
                priority = int(raw_priority)
        except (TypeError, ValueError):
            priority = None

        candidates.append(
            ClaimCandidateSchema(
                claim_text=claim_text,
                claim_source=ClaimSourceType.PLANNER_QUERY,
                aspect=_normalize_claim_text(raw_query.get("aspect")) or None,
                priority=priority,
                search_keywords=search_keywords[:6],
            )
        )

    deduped: OrderedDict[str, ClaimCandidateSchema] = OrderedDict()
    for candidate in sorted(candidates, key=lambda item: (item.priority or 999, item.claim_text)):
        deduped.setdefault(candidate.claim_text.casefold(), candidate)
    return list(deduped.values())


def _fallback_claim_candidates(parsed_document: dict[str, Any], *, max_claims: int) -> list[ClaimCandidateSchema]:
    """Extract lightweight claim candidates from parsed document text when planner claims are missing."""

    candidates: OrderedDict[str, ClaimCandidateSchema] = OrderedDict()
    for window in _fallback_text_windows(parsed_document):
        for sentence in SENTENCE_SPLIT_PATTERN.split(window):
            normalized_sentence = _normalize_claim_text(sentence)
            if not normalized_sentence:
                continue
            if len(normalized_sentence) < 40 or len(normalized_sentence) > 260:
                continue
            if not CLAIM_HINT_PATTERN.search(normalized_sentence):
                continue

            claim_key = normalized_sentence.casefold()
            if claim_key in candidates:
                continue

            candidates[claim_key] = ClaimCandidateSchema(
                claim_text=normalized_sentence,
                claim_source=ClaimSourceType.PARSED_TEXT_FALLBACK,
                aspect="claim_extraction_fallback",
            )
            if len(candidates) >= max_claims:
                return list(candidates.values())

    return list(candidates.values())


def extract_claim_candidates(
    review_plan: dict[str, Any],
    parsed_document: dict[str, Any],
    *,
    candidate_claims: Sequence[dict[str, Any]] | None = None,
    max_claims: int = DEFAULT_MAX_CLAIMS,
) -> list[ClaimCandidateSchema]:
    """Source candidate claims, preferring planner queries and falling back to parsed text."""

    if candidate_claims:
        validated_candidates = [_candidate_from_dict(candidate) for candidate in candidate_claims]
        return validated_candidates[:max_claims]

    planner_candidates = _planner_claim_candidates(review_plan)
    if planner_candidates:
        return planner_candidates[:max_claims]

    return _fallback_claim_candidates(parsed_document, max_claims=max_claims)


def build_claim_verification_scaffold(
    review_plan: dict[str, Any],
    evidences: list[dict[str, Any]],
    *,
    parsed_document: dict[str, Any] | None = None,
    candidate_claims: Sequence[dict[str, Any]] | None = None,
    max_claims: int = DEFAULT_MAX_CLAIMS,
) -> list[dict[str, Any]]:
    """Create deterministic claim-verification objects directly from retrieved evidence."""

    parsed_document = parsed_document or {}
    candidates = extract_claim_candidates(
        review_plan,
        parsed_document,
        candidate_claims=candidate_claims,
        max_claims=max_claims,
    )
    grouped_evidences = _group_evidences_by_claim(evidences)

    scaffold: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_evidences = grouped_evidences.get(candidate.claim_text.casefold(), [])
        internal_payload = _fallback_internal_assessment(
            candidate_evidences[:MAX_EVIDENCES_PER_CLAIM],
            external_check_reason=_external_check_reason(candidate.claim_text),
        )
        scaffold.append(
            _finalize_internal_verification(
                internal_payload,
                candidate=candidate,
                evidences=candidate_evidences[:MAX_EVIDENCES_PER_CLAIM],
                internal_latency_ms=0.0,
            )
        )

    return scaffold


def merge_claim_verifications_with_scaffold(
    claim_verifications: list[dict[str, Any]],
    scaffold: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Backfill missing evidence lineage and audit fields from a deterministic scaffold."""

    scaffold_by_claim = {
        _normalize_claim_text(item.get("claim_text")).casefold(): item
        for item in scaffold
        if _normalize_claim_text(item.get("claim_text"))
    }

    merged: list[dict[str, Any]] = []
    seen_claims: set[str] = set()

    for verification in claim_verifications:
        claim_key = _normalize_claim_text(verification.get("claim_text")).casefold()
        scaffold_item = scaffold_by_claim.get(claim_key, {})

        merged_item = dict(verification)
        for field_name in (
            "evidence_chunk_ids",
            "evidence_quotes",
            "page_numbers",
            "section_names",
            "linked_image_paths",
        ):
            if not merged_item.get(field_name):
                merged_item[field_name] = list(scaffold_item.get(field_name, []))
        if merged_item.get("notes") in {None, ""}:
            merged_item["notes"] = scaffold_item.get("notes")
        if merged_item.get("confidence") in {None, ""} and scaffold_item.get("confidence") is not None:
            merged_item["confidence"] = scaffold_item["confidence"]
        if merged_item.get("internal_verdict") in {None, ""}:
            merged_item["internal_verdict"] = scaffold_item.get("internal_verdict")
        if merged_item.get("internal_confidence") in {None, ""}:
            merged_item["internal_confidence"] = scaffold_item.get("internal_confidence")
        if not merged_item.get("external_check_reason"):
            merged_item["external_check_reason"] = scaffold_item.get("external_check_reason")
        if not merged_item.get("claim_source"):
            merged_item["claim_source"] = scaffold_item.get("claim_source", ClaimSourceType.PLANNER_QUERY.value)
        if merged_item.get("aspect") in {None, ""}:
            merged_item["aspect"] = scaffold_item.get("aspect")

        merged.append(ClaimVerificationSchema.model_validate(merged_item).model_dump(mode="json"))
        if claim_key:
            seen_claims.add(claim_key)

    for claim_key, scaffold_item in scaffold_by_claim.items():
        if claim_key in seen_claims:
            continue
        merged.append(ClaimVerificationSchema.model_validate(scaffold_item).model_dump(mode="json"))

    return merged


def _prepare_evidence_prompt_payload(evidences: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize retrieved evidence objects into a compact prompt payload."""

    payload: list[dict[str, Any]] = []
    for evidence in _sorted_evidences(evidences)[:MAX_EVIDENCES_PER_CLAIM]:
        chunk_text = " ".join(str(evidence.get("chunk_text") or "").split())
        payload.append(
            {
                "chunk_id": str(evidence.get("chunk_id") or ""),
                "page_number": evidence.get("page_number"),
                "section_name": evidence.get("section_name"),
                "score": evidence.get("confidence_score") or evidence.get("score"),
                "linked_image_path": evidence.get("linked_image_path"),
                "chunk_text": shorten(chunk_text, width=1200, placeholder="...") if chunk_text else "",
            }
        )
    return payload


def _verify_single_claim(
    client: Any,
    *,
    parsed_document: dict[str, Any],
    candidate: ClaimCandidateSchema,
    evidences: Sequence[dict[str, Any]],
    external_check_reason: str | None,
) -> dict[str, Any]:
    """Run a model-based internal claim verification pass for one candidate claim."""

    title = str(parsed_document.get("title") or "Untitled Document")
    excerpt = _abstract_or_excerpt(parsed_document, limit=1600)
    evidence_payload = _prepare_evidence_prompt_payload(evidences)

    system_prompt = (
        "You are an evidence-grounded academic claim verifier. "
        "Judge one claim using only the supplied internal paper evidence. "
        "Do not use outside knowledge. "
        "Use supported only when the retrieved paper evidence directly and sufficiently supports the claim. "
        "Use partially_supported when the evidence supports only part of the claim or leaves material ambiguity. "
        "Use unsupported when the retrieved paper evidence directly contradicts the claim. "
        "Use missing_evidence when the paper does not provide enough relevant evidence. "
        "Use needs_external_verification when the claim depends on external literature, broad SOTA context, "
        "citation coverage, repository availability, or another outside-world check that internal paper evidence cannot settle. "
        "Set needs_external_check to true whenever such external validation would materially affect confidence. "
        "Return only the structured internal claim assessment."
    )

    user_prompt = (
        f"Paper title:\n{title}\n\n"
        f"Abstract or excerpt:\n{excerpt}\n\n"
        f"Candidate claim:\n{candidate.claim_text}\n\n"
        f"Claim source:\n{candidate.claim_source.value}\n\n"
        f"Claim aspect:\n{candidate.aspect or 'unknown'}\n\n"
        f"Potential external-check hint:\n{external_check_reason or 'None'}\n\n"
        f"Retrieved internal evidences:\n{json.dumps(evidence_payload, ensure_ascii=False)}\n\n"
        "Use the retrieved evidence text and provenance fields directly. "
        "Do not invent evidence quotes, pages, or image links."
    )

    response = client.responses.parse(
        model=CLAIM_VERIFIER_MODEL,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        text_format=InternalClaimAssessmentSchema,
        temperature=0.1,
        max_output_tokens=500,
    )
    verification = response.output_parsed
    if verification is None:
        raise RuntimeError("Claim verifier returned no structured internal verification output.")
    return verification.model_dump(mode="json")


def _finalize_internal_verification(
    internal_payload: dict[str, Any],
    *,
    candidate: ClaimCandidateSchema,
    evidences: Sequence[dict[str, Any]],
    internal_latency_ms: float,
) -> dict[str, Any]:
    """Attach authoritative internal lineage and timing to a verification payload."""

    lineage = _evidence_lineage_payload(evidences)
    internal_assessment = InternalClaimAssessmentSchema.model_validate(internal_payload)
    return ClaimVerificationSchema(
        claim_text=candidate.claim_text,
        claim_source=candidate.claim_source,
        aspect=candidate.aspect,
        verdict=internal_assessment.verdict,
        confidence=internal_assessment.confidence,
        evidence_chunk_ids=lineage["evidence_chunk_ids"],
        evidence_quotes=lineage["evidence_quotes"],
        page_numbers=lineage["page_numbers"],
        section_names=lineage["section_names"],
        linked_image_paths=lineage["linked_image_paths"],
        internal_verdict=internal_assessment.verdict,
        internal_confidence=internal_assessment.confidence,
        needs_external_check=internal_assessment.needs_external_check,
        external_check_reason=internal_assessment.external_check_reason,
        external_verification_status=ExternalCheckStatus.NOT_NEEDED,
        external_checks_run=[],
        external_evidence_records=[],
        external_source_urls=[],
        external_check_summary=None,
        external_resolution_status=ExternalResolutionStatus.NOT_APPLICABLE,
        verdict_changed_by_external=False,
        verdict_change_reason=None,
        internal_latency_ms=round(max(internal_latency_ms, 0.0), 2),
        external_latency_ms=0.0,
        notes=internal_assessment.notes,
    ).model_dump(mode="json")


def _needs_targeted_retrieval(evidences: Sequence[dict[str, Any]]) -> bool:
    """Decide whether the verifier should refresh evidence for a claim."""

    if not evidences:
        return True
    strongest_score = float(evidences[0].get("confidence_score") or evidences[0].get("score") or 0.0)
    return strongest_score < CLAIM_RETRIEVAL_REFRESH_THRESHOLD


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    deduped: OrderedDict[str, str] = OrderedDict()
    for value in values:
        normalized_value = _normalize_claim_text(value)
        if not normalized_value:
            continue
        deduped.setdefault(normalized_value.casefold(), normalized_value)
    return list(deduped.values())


def _extract_github_url(parsed_document: dict[str, Any], evidences: Sequence[dict[str, Any]]) -> str | None:
    """Find a GitHub repository URL from the claim's evidence neighborhood or paper text."""

    text_windows: list[str] = []
    for evidence in _sorted_evidences(evidences)[:MAX_EVIDENCES_PER_CLAIM]:
        text_windows.append(str(evidence.get("chunk_text") or ""))

    excerpt = _abstract_or_excerpt(parsed_document, limit=5000)
    if excerpt:
        text_windows.append(excerpt)

    full_text = str(parsed_document.get("full_text") or "")
    if full_text:
        text_windows.append(full_text[:12000])

    for window in text_windows:
        match = GITHUB_URL_PATTERN.search(window)
        if match:
            return match.group(0).rstrip(").,;")
    return None


def _build_literature_query(candidate: ClaimCandidateSchema) -> str:
    """Create a compact claim-scoped literature query."""

    query_parts = [candidate.claim_text]
    if candidate.aspect:
        query_parts.append(candidate.aspect)
    query_parts.extend(candidate.search_keywords[:4])
    return shorten(" ".join(_dedupe_strings(query_parts)), width=180, placeholder="...")


def _select_external_tool_requests(
    *,
    candidate: ClaimCandidateSchema,
    parsed_document: dict[str, Any],
    evidences: Sequence[dict[str, Any]],
    verification: dict[str, Any],
) -> tuple[list[ExternalToolRequestSchema], str | None]:
    """Choose a small deterministic set of claim-scoped external checks."""

    claim_text = candidate.claim_text
    external_reason = _normalize_claim_text(
        verification.get("external_check_reason") or _external_check_reason(claim_text)
    )
    routing_text = " ".join(value for value in (claim_text, external_reason) if value)
    requests: list[ExternalToolRequestSchema] = []

    if CODE_CHECK_PATTERN.search(routing_text):
        repo_url = _extract_github_url(parsed_document, evidences)
        if not repo_url:
            return [], "Claim references public code or reproducibility, but no GitHub repository URL was present in the parsed paper."
        requests.append(
            ExternalToolRequestSchema(
                tool_name=ExternalToolName.CHECK_GITHUB_REPO,
                rationale="Code and reproducibility claims should only use the GitHub repository checker when a concrete repository URL is present.",
                request_payload={"repo_url": repo_url},
            )
        )
        return requests, None

    if not LITERATURE_CHECK_PATTERN.search(routing_text):
        return [], "No conservative external-tool route is implemented for this flagged claim type yet."

    literature_query = _build_literature_query(candidate)
    requests.append(
        ExternalToolRequestSchema(
            tool_name=ExternalToolName.SEARCH_SEMANTIC_SCHOLAR,
            rationale="Broad literature, citation, and comparison claims should check the broader Semantic Scholar graph first.",
            request_payload={"query": literature_query, "limit": 3},
        )
    )

    if NOVELTY_CHECK_PATTERN.search(routing_text):
        requests.append(
            ExternalToolRequestSchema(
                tool_name=ExternalToolName.SEARCH_ARXIV,
                rationale="Novelty-style claims benefit from a lightweight ArXiv check for nearby recent preprints.",
                request_payload={"query": literature_query, "max_results": 3},
            )
        )

    return requests[:MAX_EXTERNAL_TOOLS_PER_CLAIM], None


def _run_external_checks(
    *,
    requests: Sequence[ExternalToolRequestSchema],
    claim_text: str,
) -> list[dict[str, Any]]:
    """Execute deterministic claim-scoped external checks through the MCP boundary."""

    check_records: list[dict[str, Any]] = []
    for request in requests:
        raw_output = execute_mcp_tool_sync(request.tool_name.value, dict(request.request_payload))
        normalized_output = normalize_external_tool_output(
            tool_name=request.tool_name,
            raw_output=raw_output,
            request_payload=dict(request.request_payload),
            claim_text=claim_text,
        )
        check_records.append(
            ClaimExternalCheckSchema(
                tool_name=request.tool_name,
                status=ExternalCheckStatus(str(normalized_output.get("status") or ExternalCheckStatus.FAILED.value)),
                rationale=request.rationale,
                request_payload=dict(request.request_payload),
                summary=(
                    shorten(str(normalized_output.get("summary") or "").strip(), width=MAX_EXTERNAL_SUMMARY_CHARS, placeholder="...")
                    if str(normalized_output.get("summary") or "").strip()
                    else shorten(_clean_tool_text(raw_output), width=MAX_EXTERNAL_SUMMARY_CHARS, placeholder="...")
                ),
                raw_output=shorten(raw_output.strip(), width=MAX_EXTERNAL_RAW_OUTPUT_CHARS, placeholder="..."),
                source_urls=[str(url) for url in normalized_output.get("source_urls") or []],
                normalized_evidence=list(normalized_output.get("normalized_evidence") or []),
            ).model_dump(mode="json")
        )
    return check_records


def _aggregate_external_source_urls(check_records: Sequence[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for record in check_records:
        urls.extend(str(url) for url in record.get("source_urls") or [])
        for evidence_record in record.get("normalized_evidence") or []:
            source_url = evidence_record.get("source_url")
            if source_url:
                urls.append(str(source_url))
    return _dedupe_strings(urls)


def _aggregate_external_evidence_records(check_records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for check_record in check_records:
        for evidence_record in check_record.get("normalized_evidence") or []:
            if isinstance(evidence_record, dict):
                records.append(evidence_record)
    return records


def _combine_notes(*notes: str | None) -> str | None:
    values = [_normalize_claim_text(note) for note in notes if _normalize_claim_text(note)]
    if not values:
        return None
    return " ".join(values)


def _augment_with_external_checks(
    *,
    parsed_document: dict[str, Any],
    candidate: ClaimCandidateSchema,
    evidences: Sequence[dict[str, Any]],
    verification: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    """Run deterministic external tool routing and merge results back into one claim verification."""

    requests, skipped_reason = _select_external_tool_requests(
        candidate=candidate,
        parsed_document=parsed_document,
        evidences=evidences,
        verification=verification,
    )
    if not requests:
        updated_verification = dict(verification)
        updated_verification["external_verification_status"] = ExternalCheckStatus.SKIPPED.value
        updated_verification["external_check_summary"] = skipped_reason
        updated_verification["external_checks_run"] = []
        updated_verification["external_evidence_records"] = []
        updated_verification["external_source_urls"] = []
        updated_verification["external_resolution_status"] = ExternalResolutionStatus.STILL_UNRESOLVED.value
        updated_verification["verdict_changed_by_external"] = False
        updated_verification["verdict_change_reason"] = skipped_reason
        updated_verification["notes"] = _combine_notes(verification.get("notes"), skipped_reason)
        return ClaimVerificationSchema.model_validate(updated_verification).model_dump(mode="json"), 0

    check_records = _run_external_checks(requests=requests, claim_text=candidate.claim_text)
    external_evidence_records = _aggregate_external_evidence_records(check_records)
    source_urls = _aggregate_external_source_urls(check_records)
    resolution_payload = resolve_external_evidence(
        claim_text=candidate.claim_text,
        internal_verdict=ClaimVerificationVerdict(str(verification.get("internal_verdict") or verification.get("verdict"))),
        internal_confidence=float(verification.get("internal_confidence") or verification.get("confidence") or 0.0),
        current_needs_external_check=bool(verification.get("needs_external_check")),
        evidence_records=external_evidence_records,
    )
    status = (
        ExternalCheckStatus.COMPLETED
        if any(str(record.get("status") or "") == ExternalCheckStatus.COMPLETED.value for record in check_records)
        else ExternalCheckStatus.FAILED
    )
    updated_verification = dict(verification)
    updated_verification["verdict"] = resolution_payload["final_verdict"]
    updated_verification["confidence"] = resolution_payload["final_confidence"]
    updated_verification["needs_external_check"] = resolution_payload["needs_external_check"]
    updated_verification["external_verification_status"] = status.value
    updated_verification["external_checks_run"] = [
        ClaimExternalCheckSchema.model_validate(record).model_dump(mode="json")
        for record in check_records
    ]
    updated_verification["external_evidence_records"] = external_evidence_records
    updated_verification["external_source_urls"] = source_urls
    updated_verification["external_check_summary"] = resolution_payload.get("external_check_summary")
    updated_verification["external_resolution_status"] = resolution_payload.get("external_resolution_status")
    updated_verification["verdict_changed_by_external"] = (
        str(updated_verification.get("internal_verdict") or "") != str(updated_verification.get("verdict") or "")
    )
    updated_verification["verdict_change_reason"] = resolution_payload.get("verdict_change_reason")
    updated_verification["notes"] = _combine_notes(
        verification.get("notes"),
        resolution_payload.get("verdict_change_reason"),
    )
    return ClaimVerificationSchema.model_validate(updated_verification).model_dump(mode="json"), len(check_records)


def _mark_external_checks_skipped(verification: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """Mark a flagged claim as unresolved because no external checks were run in this strategy."""

    updated_verification = dict(verification)
    updated_verification["external_verification_status"] = ExternalCheckStatus.SKIPPED.value
    updated_verification["external_check_summary"] = reason
    updated_verification["external_checks_run"] = []
    updated_verification["external_evidence_records"] = []
    updated_verification["external_source_urls"] = []
    updated_verification["external_resolution_status"] = ExternalResolutionStatus.STILL_UNRESOLVED.value
    updated_verification["verdict_changed_by_external"] = False
    updated_verification["verdict_change_reason"] = reason
    updated_verification["notes"] = _combine_notes(verification.get("notes"), reason)
    return ClaimVerificationSchema.model_validate(updated_verification).model_dump(mode="json")


def _verify_candidates(
    *,
    parsed_document: dict[str, Any],
    candidates: Sequence[ClaimCandidateSchema],
    base_evidences: Sequence[dict[str, Any]],
    retrieve_for_candidate: Callable[[ClaimCandidateSchema, bool], list[dict[str, Any]]],
    enable_external_checks: bool,
) -> dict[str, Any]:
    """Core verification loop shared by the worker path and benchmark path."""

    client = _get_openai_client()
    aggregated_evidences = list(base_evidences)
    grouped_evidences = _group_evidences_by_claim(aggregated_evidences)
    claim_verifications: list[dict[str, Any]] = []
    total_internal_latency_ms = 0.0
    total_external_latency_ms = 0.0
    claims_needing_external_check = 0
    claims_with_external_checks = 0
    external_checks_run = 0

    for candidate in candidates:
        claim_key = candidate.claim_text.casefold()
        candidate_evidences = grouped_evidences.get(claim_key, [])[:MAX_EVIDENCES_PER_CLAIM]

        if _needs_targeted_retrieval(candidate_evidences):
            refreshed_evidences = retrieve_for_candidate(candidate, bool(candidate_evidences))
            aggregated_evidences = _merge_evidence_sets(aggregated_evidences, refreshed_evidences)
            grouped_evidences = _group_evidences_by_claim(aggregated_evidences)
            candidate_evidences = grouped_evidences.get(claim_key, [])[:MAX_EVIDENCES_PER_CLAIM]

        external_check_reason = _external_check_reason(candidate.claim_text)
        internal_started_at = perf_counter()
        try:
            internal_payload = _verify_single_claim(
                client,
                parsed_document=parsed_document,
                candidate=candidate,
                evidences=candidate_evidences,
                external_check_reason=external_check_reason,
            )
        except (openai.AuthenticationError, openai.RateLimitError):
            raise
        except Exception as exc:
            internal_payload = _fallback_internal_assessment(
                candidate_evidences,
                external_check_reason=external_check_reason,
                error_message=str(exc),
            )
        internal_latency_ms = round((perf_counter() - internal_started_at) * 1000, 2)
        total_internal_latency_ms += internal_latency_ms

        verification = _finalize_internal_verification(
            internal_payload,
            candidate=candidate,
            evidences=candidate_evidences,
            internal_latency_ms=internal_latency_ms,
        )

        if verification.get("needs_external_check"):
            claims_needing_external_check += 1

        if verification.get("needs_external_check") and enable_external_checks:
            external_started_at = perf_counter()
            verification, tool_count = _augment_with_external_checks(
                parsed_document=parsed_document,
                candidate=candidate,
                evidences=candidate_evidences,
                verification=verification,
            )
            external_latency_ms = round((perf_counter() - external_started_at) * 1000, 2)
            verification["external_latency_ms"] = external_latency_ms
            total_external_latency_ms += external_latency_ms
            if tool_count:
                claims_with_external_checks += 1
                external_checks_run += tool_count
        elif verification.get("needs_external_check"):
            verification = _mark_external_checks_skipped(
                verification,
                reason="External checks were disabled for this run, so the claim remains internally unresolved.",
            )

        claim_verifications.append(
            ClaimVerificationSchema.model_validate(verification).model_dump(mode="json")
        )

    summary = ClaimVerificationRunSummarySchema(
        total_claims=len(candidates),
        claims_needing_external_check=claims_needing_external_check,
        claims_with_external_checks=claims_with_external_checks,
        external_checks_run=external_checks_run,
        internal_latency_ms=round(total_internal_latency_ms, 2),
        external_latency_ms=round(total_external_latency_ms, 2),
    ).model_dump(mode="json")

    return {
        "claim_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "claim_verifications": claim_verifications,
        "claim_verification_summary": summary,
        "evidences": _merge_evidence_sets(aggregated_evidences),
    }


def verify_claims_for_document(
    *,
    parsed_document: dict[str, Any],
    review_plan: dict[str, Any],
    evidences: Sequence[dict[str, Any]],
    document_id: Any,
    candidate_claims: Sequence[dict[str, Any]] | None = None,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    enable_external_checks: bool = False,
) -> dict[str, Any]:
    """Run the dedicated claim verification stage against a persisted document."""

    candidates = extract_claim_candidates(
        review_plan,
        parsed_document,
        candidate_claims=candidate_claims,
        max_claims=max_claims,
    )

    def retrieve_for_candidate(candidate: ClaimCandidateSchema, broaden: bool) -> list[dict[str, Any]]:
        claim_plan = _claim_plan_for_candidate(candidate, review_plan)
        refreshed_evidences = retriever.retrieve_evidences(document_id, claim_plan, broaden=broaden)
        if not refreshed_evidences and not broaden:
            refreshed_evidences = retriever.retrieve_evidences(document_id, claim_plan, broaden=True)
        return refreshed_evidences

    return _verify_candidates(
        parsed_document=parsed_document,
        candidates=candidates,
        base_evidences=evidences,
        retrieve_for_candidate=retrieve_for_candidate,
        enable_external_checks=enable_external_checks,
    )


def verify_claims_from_chunks(
    *,
    parsed_document: dict[str, Any],
    review_plan: dict[str, Any],
    chunks: Sequence[dict[str, Any]],
    chunk_embeddings: Sequence[Sequence[float]],
    evidences: Sequence[dict[str, Any]] | None = None,
    candidate_claims: Sequence[dict[str, Any]] | None = None,
    max_claims: int = DEFAULT_MAX_CLAIMS,
    enable_external_checks: bool = False,
) -> dict[str, Any]:
    """Run the dedicated claim verification stage against in-memory chunk payloads."""

    candidates = extract_claim_candidates(
        review_plan,
        parsed_document,
        candidate_claims=candidate_claims,
        max_claims=max_claims,
    )
    base_evidences = list(evidences or [])

    def retrieve_for_candidate(candidate: ClaimCandidateSchema, broaden: bool) -> list[dict[str, Any]]:
        claim_plan = _claim_plan_for_candidate(candidate, review_plan)
        refreshed_evidences = retriever.retrieve_evidences_from_chunks(
            chunks,
            chunk_embeddings,
            claim_plan,
            broaden=broaden,
        )
        if not refreshed_evidences and not broaden:
            refreshed_evidences = retriever.retrieve_evidences_from_chunks(
                chunks,
                chunk_embeddings,
                claim_plan,
                broaden=True,
            )
        return refreshed_evidences

    return _verify_candidates(
        parsed_document=parsed_document,
        candidates=candidates,
        base_evidences=base_evidences,
        retrieve_for_candidate=retrieve_for_candidate,
        enable_external_checks=enable_external_checks,
    )
