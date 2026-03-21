"""Pydantic schemas for review task creation and polling endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .enums import (
    ClaimSourceType,
    ClaimVerificationVerdict,
    ExternalEvidenceImpact,
    ExternalEvidenceMatchStatus,
    ExternalCheckStatus,
    ExternalResolutionStatus,
    ExternalSupportStrength,
    ExternalToolName,
    ReviewTaskStatus,
)


class ExternalReferenceSchema(BaseModel):
    """A related paper retrieved from ArXiv during external verification."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    summary: str | None = None
    citation_count: int | None = None
    influential_citation_count: int | None = None


class ClaimExternalCheckSchema(BaseModel):
    """One claim-scoped external check executed by the verifier."""

    model_config = ConfigDict(from_attributes=True)

    tool_name: ExternalToolName
    status: ExternalCheckStatus
    rationale: str | None = None
    request_payload: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    raw_output: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    normalized_evidence: list["ExternalEvidenceRecordSchema"] = Field(default_factory=list)


class GitHubExternalEvidencePayloadSchema(BaseModel):
    """Normalized GitHub repository evidence for reproducibility checks."""

    model_config = ConfigDict(from_attributes=True)

    repo_url: str | None = None
    repo_exists: bool | None = None
    owner: str | None = None
    name: str | None = None
    default_branch: str | None = None
    stars: int | None = None
    watchers: int | None = None
    forks: int | None = None
    has_readme: bool | None = None
    has_releases: bool | None = None
    last_updated: str | None = None
    pushed_at: str | None = None
    primary_language: str | None = None
    languages: list[str] = Field(default_factory=list)
    archived: bool | None = None
    disabled: bool | None = None
    open_issues_count: int | None = None
    summary: str | None = None


class SemanticScholarExternalEvidencePayloadSchema(BaseModel):
    """Normalized Semantic Scholar evidence for literature checks."""

    model_config = ConfigDict(from_attributes=True)

    query: str | None = None
    matched_paper_title: str | None = None
    matched_authors: list[str] = Field(default_factory=list)
    year: int | None = None
    citation_count: int | None = None
    influential_citation_count: int | None = None
    venue: str | None = None
    source_url: str | None = None
    paper_id: str | None = None
    result_rank: int | None = None
    match_status: ExternalEvidenceMatchStatus = ExternalEvidenceMatchStatus.UNKNOWN
    summary: str | None = None


class ArxivExternalEvidencePayloadSchema(BaseModel):
    """Normalized ArXiv evidence for novelty-style checks."""

    model_config = ConfigDict(from_attributes=True)

    query: str | None = None
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_date: str | None = None
    arxiv_id: str | None = None
    categories: list[str] = Field(default_factory=list)
    source_url: str | None = None
    result_rank: int | None = None
    match_status: ExternalEvidenceMatchStatus = ExternalEvidenceMatchStatus.UNKNOWN
    summary: str | None = None


class ExternalEvidenceRecordSchema(BaseModel):
    """One normalized typed external evidence record attached to a claim."""

    model_config = ConfigDict(from_attributes=True)

    tool_name: ExternalToolName
    source_url: str | None = None
    source_id: str | None = None
    match_status: ExternalEvidenceMatchStatus = ExternalEvidenceMatchStatus.UNKNOWN
    support_assessment: ExternalEvidenceImpact = ExternalEvidenceImpact.UNRESOLVED
    support_strength: ExternalSupportStrength = ExternalSupportStrength.UNKNOWN
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    summary: str | None = None
    github: GitHubExternalEvidencePayloadSchema | None = None
    semantic_scholar: SemanticScholarExternalEvidencePayloadSchema | None = None
    arxiv: ArxivExternalEvidencePayloadSchema | None = None


class ClaimVerificationRunSummarySchema(BaseModel):
    """Lightweight instrumentation for one claim-verification stage run."""

    model_config = ConfigDict(from_attributes=True)

    total_claims: int = Field(ge=0)
    claims_needing_external_check: int = Field(ge=0)
    claims_with_external_checks: int = Field(ge=0)
    external_checks_run: int = Field(ge=0)
    internal_latency_ms: float = Field(ge=0.0)
    external_latency_ms: float = Field(ge=0.0)


class ClaimVerificationSchema(BaseModel):
    """Structured verification record for a paper claim or review query."""

    model_config = ConfigDict(from_attributes=True)

    claim_text: str
    claim_source: ClaimSourceType = ClaimSourceType.PLANNER_QUERY
    aspect: str | None = None
    verdict: ClaimVerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    section_names: list[str] = Field(default_factory=list)
    linked_image_paths: list[str] = Field(default_factory=list)
    internal_verdict: ClaimVerificationVerdict | None = None
    internal_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    needs_external_check: bool = False
    external_check_reason: str | None = None
    external_verification_status: ExternalCheckStatus = ExternalCheckStatus.NOT_NEEDED
    external_checks_run: list[ClaimExternalCheckSchema] = Field(default_factory=list)
    external_evidence_records: list[ExternalEvidenceRecordSchema] = Field(default_factory=list)
    external_source_urls: list[str] = Field(default_factory=list)
    external_check_summary: str | None = None
    external_resolution_status: ExternalResolutionStatus = ExternalResolutionStatus.NOT_APPLICABLE
    verdict_changed_by_external: bool = False
    verdict_change_reason: str | None = None
    internal_latency_ms: float | None = Field(default=None, ge=0.0)
    external_latency_ms: float | None = Field(default=None, ge=0.0)
    notes: str | None = None


class ReviewResultSchema(BaseModel):
    """Structured review report persisted in review_tasks.result_json."""

    model_config = ConfigDict(from_attributes=True)

    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    questions_for_authors: list[str] = Field(default_factory=list)
    code_reproducibility_check: Optional[str] = Field(
        ...,
        description=(
            "Summarize the health, accessibility, and maintenance signals of any public GitHub "
            "repository mentioned by the authors, and note gracefully if the external tool failed."
        ),
    )
    claim_verifications: list[ClaimVerificationSchema] = Field(default_factory=list)
    claim_verification_summary: ClaimVerificationRunSummarySchema | None = None
    external_references_checked: list[ExternalReferenceSchema] = Field(default_factory=list)


class ReviewCreateRequest(BaseModel):
    """Request payload for creating an asynchronous review task."""

    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    focus_areas: list[str] = Field(default_factory=list)


class ReviewCreateResponse(BaseModel):
    """Immediate acknowledgement after task creation."""

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    status: ReviewTaskStatus


class ReviewReadResponse(BaseModel):
    """Polling response for a review task."""

    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    status: ReviewTaskStatus
    result_json: ReviewResultSchema | None = None
    error_message: str | None = None
    retry_count: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
