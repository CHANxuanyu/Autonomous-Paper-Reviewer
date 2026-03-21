"""Typed normalization and conservative resolution for external claim evidence."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import Any

from schemas.enums import (
    ClaimVerificationVerdict,
    ExternalCheckStatus,
    ExternalEvidenceImpact,
    ExternalEvidenceMatchStatus,
    ExternalResolutionStatus,
    ExternalSupportStrength,
    ExternalToolName,
)
from schemas.review import (
    ArxivExternalEvidencePayloadSchema,
    ExternalEvidenceRecordSchema,
    GitHubExternalEvidencePayloadSchema,
    SemanticScholarExternalEvidencePayloadSchema,
)

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "paper",
    "method",
    "results",
    "claim",
    "using",
    "into",
    "over",
    "than",
    "their",
    "they",
    "our",
    "are",
    "was",
    "were",
    "has",
    "have",
    "code",
}
EXPLICIT_CODE_AVAILABILITY_PATTERN = re.compile(
    r"\b(publicly available|open[- ]source|code is available|release(?:d)? code|github)\b",
    re.IGNORECASE,
)
BROAD_REPRODUCIBILITY_PATTERN = re.compile(r"\b(reproducib|implementation|repository)\b", re.IGNORECASE)
NOVELTY_OR_COMPARISON_PATTERN = re.compile(
    r"\b(novel|novelty|first\b|state[- ]of[- ]the[- ]art|sota|outperform(?:s|ed)?\b|superior to prior)\b",
    re.IGNORECASE,
)


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _safe_json_object(raw_output: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_output)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _keyword_tokens(value: str | None) -> set[str]:
    tokens = {match.group(0) for match in TOKEN_PATTERN.finditer((value or "").lower())}
    return {token for token in tokens if token not in STOPWORDS and len(token) > 2}


def _keyword_overlap_score(reference_text: str | None, candidate_text: str | None) -> float:
    reference_tokens = _keyword_tokens(reference_text)
    if not reference_tokens:
        return 0.0
    candidate_tokens = _keyword_tokens(candidate_text)
    if not candidate_tokens:
        return 0.0
    overlap = reference_tokens & candidate_tokens
    return round(len(overlap) / len(reference_tokens), 4)


def _match_status_from_score(score: float) -> ExternalEvidenceMatchStatus:
    if score >= 0.65:
        return ExternalEvidenceMatchStatus.MATCHED
    if score >= 0.35:
        return ExternalEvidenceMatchStatus.PLAUSIBLE_MATCH
    if score > 0.0:
        return ExternalEvidenceMatchStatus.AMBIGUOUS_MATCH
    return ExternalEvidenceMatchStatus.UNKNOWN


def _coerce_check_status(payload: dict[str, Any] | None, raw_output: str) -> ExternalCheckStatus:
    if payload:
        status = str(payload.get("status") or "").lower()
        if status in {"ok", "no_results", "not_found"}:
            return ExternalCheckStatus.COMPLETED
        if status == "error":
            return ExternalCheckStatus.FAILED
    normalized = _normalize_text(raw_output).lower()
    if not normalized or normalized.startswith("tool error:") or "failed" in normalized:
        return ExternalCheckStatus.FAILED
    return ExternalCheckStatus.COMPLETED


def _explicit_code_claim(claim_text: str) -> bool:
    return bool(EXPLICIT_CODE_AVAILABILITY_PATTERN.search(claim_text))


def _broad_reproducibility_claim(claim_text: str) -> bool:
    return bool(BROAD_REPRODUCIBILITY_PATTERN.search(claim_text))


def _novelty_or_comparison_claim(claim_text: str) -> bool:
    return bool(NOVELTY_OR_COMPARISON_PATTERN.search(claim_text))


def _dedupe_urls(values: list[str]) -> list[str]:
    deduped: OrderedDict[str, str] = OrderedDict()
    for value in values:
        normalized_value = _normalize_text(value)
        if not normalized_value:
            continue
        deduped.setdefault(normalized_value, normalized_value)
    return list(deduped.values())


def _normalize_github_payload(
    *,
    raw_output: str,
    request_payload: dict[str, Any],
    claim_text: str,
) -> tuple[ExternalCheckStatus, str | None, list[str], list[dict[str, Any]]]:
    payload = _safe_json_object(raw_output) or {}
    repo_payload = payload.get("repo") if isinstance(payload.get("repo"), dict) else {}
    repo_exists = repo_payload.get("repo_exists")
    repo_url = _normalize_text(str(repo_payload.get("repo_url") or request_payload.get("repo_url") or "")) or None
    owner = _normalize_text(str(repo_payload.get("owner") or "")) or None
    name = _normalize_text(str(repo_payload.get("name") or "")) or None
    summary = _normalize_text(str(payload.get("summary") or raw_output))
    status = _coerce_check_status(payload, raw_output)

    support_assessment = ExternalEvidenceImpact.UNRESOLVED
    support_strength = ExternalSupportStrength.UNKNOWN
    confidence = None
    match_status = ExternalEvidenceMatchStatus.UNKNOWN

    if repo_exists is True:
        match_status = ExternalEvidenceMatchStatus.MATCHED
        confidence = 0.95
        if _explicit_code_claim(claim_text):
            support_assessment = ExternalEvidenceImpact.SUPPORTS
            support_strength = ExternalSupportStrength.STRONG
        elif _broad_reproducibility_claim(claim_text):
            support_assessment = ExternalEvidenceImpact.SUPPORTS
            support_strength = ExternalSupportStrength.MODERATE
            confidence = 0.75
    elif repo_exists is False:
        match_status = ExternalEvidenceMatchStatus.NOT_FOUND
        confidence = 0.9
        if _explicit_code_claim(claim_text):
            support_assessment = ExternalEvidenceImpact.WEAKENS
            support_strength = ExternalSupportStrength.STRONG
        elif _broad_reproducibility_claim(claim_text):
            support_assessment = ExternalEvidenceImpact.WEAKENS
            support_strength = ExternalSupportStrength.MODERATE
            confidence = 0.7
    elif status == ExternalCheckStatus.FAILED:
        match_status = ExternalEvidenceMatchStatus.ERROR

    record = ExternalEvidenceRecordSchema(
        tool_name=ExternalToolName.CHECK_GITHUB_REPO,
        source_url=repo_url,
        source_id="/".join(part for part in (owner, name) if part) or None,
        match_status=match_status,
        support_assessment=support_assessment,
        support_strength=support_strength,
        confidence=confidence,
        summary=summary or None,
        github=GitHubExternalEvidencePayloadSchema.model_validate(repo_payload or {"repo_url": repo_url}),
    ).model_dump(mode="json")

    return status, summary or None, _dedupe_urls([repo_url] if repo_url else []), [record]


def _normalize_semantic_scholar_payload(
    *,
    raw_output: str,
    request_payload: dict[str, Any],
    claim_text: str,
) -> tuple[ExternalCheckStatus, str | None, list[str], list[dict[str, Any]]]:
    payload = _safe_json_object(raw_output) or {}
    query = _normalize_text(str(payload.get("query") or request_payload.get("query") or "")) or None
    summary = _normalize_text(str(payload.get("summary") or raw_output)) or None
    status = _coerce_check_status(payload, raw_output)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []

    records: list[dict[str, Any]] = []
    if not results:
        records.append(
            ExternalEvidenceRecordSchema(
                tool_name=ExternalToolName.SEARCH_SEMANTIC_SCHOLAR,
                match_status=ExternalEvidenceMatchStatus.NOT_FOUND if status == ExternalCheckStatus.COMPLETED else ExternalEvidenceMatchStatus.ERROR,
                support_assessment=ExternalEvidenceImpact.UNRESOLVED,
                support_strength=ExternalSupportStrength.UNKNOWN,
                confidence=0.0 if status == ExternalCheckStatus.COMPLETED else None,
                summary=summary,
                semantic_scholar=SemanticScholarExternalEvidencePayloadSchema(
                    query=query,
                    match_status=ExternalEvidenceMatchStatus.NOT_FOUND if status == ExternalCheckStatus.COMPLETED else ExternalEvidenceMatchStatus.ERROR,
                    summary=summary,
                ),
            ).model_dump(mode="json")
        )
        return status, summary, [], records

    source_urls: list[str] = []
    for result in results[:3]:
        result_payload = result if isinstance(result, dict) else {}
        title = _normalize_text(str(result_payload.get("title") or "")) or None
        overlap_score = _keyword_overlap_score(query or claim_text, title)
        match_status = _match_status_from_score(overlap_score)
        support_assessment = ExternalEvidenceImpact.UNRESOLVED
        support_strength = ExternalSupportStrength.UNKNOWN
        confidence = round(overlap_score, 2) if overlap_score else 0.0

        if _novelty_or_comparison_claim(claim_text):
            if match_status == ExternalEvidenceMatchStatus.MATCHED:
                support_assessment = ExternalEvidenceImpact.WEAKENS
                support_strength = ExternalSupportStrength.MODERATE
            elif match_status == ExternalEvidenceMatchStatus.PLAUSIBLE_MATCH:
                support_assessment = ExternalEvidenceImpact.WEAKENS
                support_strength = ExternalSupportStrength.WEAK

        source_url = _normalize_text(str(result_payload.get("source_url") or "")) or None
        if source_url:
            source_urls.append(source_url)

        record_summary = (
            f"Semantic Scholar result: {title or 'Untitled'} "
            f"({result_payload.get('year') or 'unknown year'}) "
            f"with {int(result_payload.get('citation_count') or 0)} citations."
        )
        records.append(
            ExternalEvidenceRecordSchema(
                tool_name=ExternalToolName.SEARCH_SEMANTIC_SCHOLAR,
                source_url=source_url,
                source_id=_normalize_text(str(result_payload.get("paper_id") or "")) or None,
                match_status=match_status,
                support_assessment=support_assessment,
                support_strength=support_strength,
                confidence=confidence if confidence > 0.0 else None,
                summary=record_summary,
                semantic_scholar=SemanticScholarExternalEvidencePayloadSchema(
                    query=query,
                    matched_paper_title=title,
                    matched_authors=[str(author) for author in result_payload.get("authors") or []],
                    year=result_payload.get("year"),
                    citation_count=result_payload.get("citation_count"),
                    influential_citation_count=result_payload.get("influential_citation_count"),
                    venue=_normalize_text(str(result_payload.get("venue") or "")) or None,
                    source_url=source_url,
                    paper_id=_normalize_text(str(result_payload.get("paper_id") or "")) or None,
                    result_rank=result_payload.get("result_rank"),
                    match_status=match_status,
                    summary=record_summary,
                ),
            ).model_dump(mode="json")
        )

    return status, summary, _dedupe_urls(source_urls), records


def _normalize_arxiv_payload(
    *,
    raw_output: str,
    request_payload: dict[str, Any],
    claim_text: str,
) -> tuple[ExternalCheckStatus, str | None, list[str], list[dict[str, Any]]]:
    payload = _safe_json_object(raw_output) or {}
    query = _normalize_text(str(payload.get("query") or request_payload.get("query") or "")) or None
    summary = _normalize_text(str(payload.get("summary") or raw_output)) or None
    status = _coerce_check_status(payload, raw_output)
    results = payload.get("results") if isinstance(payload.get("results"), list) else []

    records: list[dict[str, Any]] = []
    if not results:
        records.append(
            ExternalEvidenceRecordSchema(
                tool_name=ExternalToolName.SEARCH_ARXIV,
                match_status=ExternalEvidenceMatchStatus.NOT_FOUND if status == ExternalCheckStatus.COMPLETED else ExternalEvidenceMatchStatus.ERROR,
                support_assessment=ExternalEvidenceImpact.UNRESOLVED,
                support_strength=ExternalSupportStrength.UNKNOWN,
                confidence=0.0 if status == ExternalCheckStatus.COMPLETED else None,
                summary=summary,
                arxiv=ArxivExternalEvidencePayloadSchema(
                    query=query,
                    match_status=ExternalEvidenceMatchStatus.NOT_FOUND if status == ExternalCheckStatus.COMPLETED else ExternalEvidenceMatchStatus.ERROR,
                    summary=summary,
                ),
            ).model_dump(mode="json")
        )
        return status, summary, [], records

    source_urls: list[str] = []
    for result in results[:3]:
        result_payload = result if isinstance(result, dict) else {}
        title = _normalize_text(str(result_payload.get("title") or "")) or None
        overlap_score = _keyword_overlap_score(query or claim_text, title)
        match_status = _match_status_from_score(overlap_score)
        support_assessment = ExternalEvidenceImpact.UNRESOLVED
        support_strength = ExternalSupportStrength.UNKNOWN
        confidence = round(overlap_score, 2) if overlap_score else 0.0

        if _novelty_or_comparison_claim(claim_text):
            if match_status == ExternalEvidenceMatchStatus.MATCHED:
                support_assessment = ExternalEvidenceImpact.WEAKENS
                support_strength = ExternalSupportStrength.WEAK
            elif match_status == ExternalEvidenceMatchStatus.PLAUSIBLE_MATCH:
                support_assessment = ExternalEvidenceImpact.WEAKENS
                support_strength = ExternalSupportStrength.WEAK

        source_url = _normalize_text(str(result_payload.get("source_url") or "")) or None
        if source_url:
            source_urls.append(source_url)

        record_summary = (
            f"ArXiv result: {title or 'Untitled'} "
            f"published on {result_payload.get('published_date') or 'an unknown date'}."
        )
        records.append(
            ExternalEvidenceRecordSchema(
                tool_name=ExternalToolName.SEARCH_ARXIV,
                source_url=source_url,
                source_id=_normalize_text(str(result_payload.get("arxiv_id") or "")) or None,
                match_status=match_status,
                support_assessment=support_assessment,
                support_strength=support_strength,
                confidence=confidence if confidence > 0.0 else None,
                summary=record_summary,
                arxiv=ArxivExternalEvidencePayloadSchema(
                    query=query,
                    title=title,
                    authors=[str(author) for author in result_payload.get("authors") or []],
                    published_date=_normalize_text(str(result_payload.get("published_date") or "")) or None,
                    arxiv_id=_normalize_text(str(result_payload.get("arxiv_id") or "")) or None,
                    categories=[str(category) for category in result_payload.get("categories") or []],
                    source_url=source_url,
                    result_rank=result_payload.get("result_rank"),
                    match_status=match_status,
                    summary=record_summary,
                ),
            ).model_dump(mode="json")
        )

    return status, summary, _dedupe_urls(source_urls), records


def normalize_external_tool_output(
    *,
    tool_name: ExternalToolName,
    raw_output: str,
    request_payload: dict[str, Any],
    claim_text: str,
) -> dict[str, Any]:
    """Normalize one raw external tool output into typed evidence records."""

    if tool_name == ExternalToolName.CHECK_GITHUB_REPO:
        status, summary, source_urls, records = _normalize_github_payload(
            raw_output=raw_output,
            request_payload=request_payload,
            claim_text=claim_text,
        )
    elif tool_name == ExternalToolName.SEARCH_SEMANTIC_SCHOLAR:
        status, summary, source_urls, records = _normalize_semantic_scholar_payload(
            raw_output=raw_output,
            request_payload=request_payload,
            claim_text=claim_text,
        )
    elif tool_name == ExternalToolName.SEARCH_ARXIV:
        status, summary, source_urls, records = _normalize_arxiv_payload(
            raw_output=raw_output,
            request_payload=request_payload,
            claim_text=claim_text,
        )
    else:
        status = ExternalCheckStatus.FAILED
        summary = _normalize_text(raw_output) or "Unsupported external tool output."
        source_urls = []
        records = []

    return {
        "status": status.value,
        "summary": summary,
        "source_urls": source_urls,
        "normalized_evidence": records,
    }


def _strongest_record(
    records: list[dict[str, Any]],
    impact: ExternalEvidenceImpact,
) -> dict[str, Any] | None:
    strength_order = {
        ExternalSupportStrength.STRONG.value: 3,
        ExternalSupportStrength.MODERATE.value: 2,
        ExternalSupportStrength.WEAK.value: 1,
        ExternalSupportStrength.UNKNOWN.value: 0,
    }
    matching_records = [record for record in records if record.get("support_assessment") == impact.value]
    if not matching_records:
        return None
    return max(
        matching_records,
        key=lambda record: (
            strength_order.get(str(record.get("support_strength") or ExternalSupportStrength.UNKNOWN.value), 0),
            float(record.get("confidence") or 0.0),
        ),
    )


def _record_summary(record: dict[str, Any]) -> str | None:
    return _normalize_text(str(record.get("summary") or "")) or None


def resolve_external_evidence(
    *,
    claim_text: str,
    internal_verdict: ClaimVerificationVerdict,
    internal_confidence: float,
    current_needs_external_check: bool,
    evidence_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge typed external evidence into a conservative claim-level resolution."""

    strong_support = _strongest_record(evidence_records, ExternalEvidenceImpact.SUPPORTS)
    strong_weaken = _strongest_record(evidence_records, ExternalEvidenceImpact.WEAKENS)
    explicit_code_claim = _explicit_code_claim(claim_text)
    broad_repro_claim = _broad_reproducibility_claim(claim_text)

    final_verdict = internal_verdict
    final_confidence = internal_confidence
    needs_external_check = current_needs_external_check
    resolution_status = ExternalResolutionStatus.STILL_UNRESOLVED if evidence_records else ExternalResolutionStatus.NOT_APPLICABLE
    verdict_change_reason: str | None = None

    if explicit_code_claim and strong_support and strong_support.get("tool_name") == ExternalToolName.CHECK_GITHUB_REPO.value:
        final_verdict = ClaimVerificationVerdict.SUPPORTED
        final_confidence = max(internal_confidence, 0.9)
        needs_external_check = False
        resolution_status = (
            ExternalResolutionStatus.REINFORCED_INTERNAL
            if internal_verdict == ClaimVerificationVerdict.SUPPORTED
            else ExternalResolutionStatus.CHANGED_VERDICT
        )
        verdict_change_reason = "A reachable GitHub repository directly supports the claim that public code is available."
    elif explicit_code_claim and strong_weaken and strong_weaken.get("tool_name") == ExternalToolName.CHECK_GITHUB_REPO.value:
        final_verdict = ClaimVerificationVerdict.UNSUPPORTED
        final_confidence = max(internal_confidence, 0.85)
        needs_external_check = False
        resolution_status = (
            ExternalResolutionStatus.REINFORCED_INTERNAL
            if internal_verdict == ClaimVerificationVerdict.UNSUPPORTED
            else ExternalResolutionStatus.CHANGED_VERDICT
        )
        verdict_change_reason = "The claimed GitHub repository could not be verified, which weakens an explicit public-code availability claim."
    elif broad_repro_claim and strong_support and strong_support.get("tool_name") == ExternalToolName.CHECK_GITHUB_REPO.value:
        if internal_verdict in {ClaimVerificationVerdict.MISSING_EVIDENCE, ClaimVerificationVerdict.NEEDS_EXTERNAL_VERIFICATION}:
            final_verdict = ClaimVerificationVerdict.PARTIALLY_SUPPORTED
            resolution_status = ExternalResolutionStatus.CHANGED_VERDICT
        else:
            resolution_status = ExternalResolutionStatus.REINFORCED_INTERNAL
        final_confidence = max(internal_confidence, 0.72)
        needs_external_check = False
        verdict_change_reason = "A reachable repository improves confidence in the paper's reproducibility-related claim."
    elif broad_repro_claim and strong_weaken and strong_weaken.get("tool_name") == ExternalToolName.CHECK_GITHUB_REPO.value:
        if internal_verdict == ClaimVerificationVerdict.SUPPORTED:
            final_verdict = ClaimVerificationVerdict.PARTIALLY_SUPPORTED
            resolution_status = ExternalResolutionStatus.WEAKENED_INTERNAL
            final_confidence = min(max(internal_confidence - 0.15, 0.45), internal_confidence)
            needs_external_check = False
            verdict_change_reason = "Repository verification weakened the reproducibility claim, but did not fully settle broader implementation questions."
        else:
            resolution_status = ExternalResolutionStatus.STILL_UNRESOLVED
            verdict_change_reason = "Repository verification weakened the claim, but the external evidence is not decisive enough to fully resolve it."
    else:
        record_summary = _record_summary(strong_support or strong_weaken or (evidence_records[0] if evidence_records else {}))
        verdict_change_reason = record_summary or "External checks did not produce decisive evidence."

    external_check_summary_parts = [
        _record_summary(record)
        for record in evidence_records[:3]
        if _record_summary(record)
    ]
    if verdict_change_reason and verdict_change_reason not in external_check_summary_parts:
        external_check_summary_parts.append(verdict_change_reason)
    external_check_summary = " ".join(external_check_summary_parts).strip() or None

    if resolution_status == ExternalResolutionStatus.STILL_UNRESOLVED:
        needs_external_check = True

    return {
        "final_verdict": final_verdict.value,
        "final_confidence": round(final_confidence, 2),
        "needs_external_check": needs_external_check,
        "external_check_summary": external_check_summary,
        "external_resolution_status": resolution_status.value,
        "verdict_change_reason": verdict_change_reason,
    }
