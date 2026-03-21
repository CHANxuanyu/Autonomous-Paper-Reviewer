"""Shared API enums derived from the design document."""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """String enum base for clean JSON serialization."""


class DocumentStatus(StrEnum):
    """Lifecycle states for an uploaded document."""

    UPLOADED = "UPLOADED"
    PARSED = "PARSED"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


class ReviewTaskStatus(StrEnum):
    """Workflow states for the asynchronous review task."""

    PENDING = "PENDING"
    PARSING_DOC = "PARSING_DOC"
    VECTORIZING = "VECTORIZING"
    AGENT_PLANNING = "AGENT_PLANNING"
    EVIDENCE_RETRIEVAL = "EVIDENCE_RETRIEVAL"
    CLAIM_VERIFICATION = "CLAIM_VERIFICATION"
    REPORT_GENERATING = "REPORT_GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UserTier(StrEnum):
    """Current user plan levels mentioned by the document."""

    FREE = "free"
    PRO = "pro"
    ADMIN = "admin"


class EvidenceType(StrEnum):
    """Supported evidence classifications for review claims."""

    FACT = "fact"
    CONCERN = "concern"
    SUGGESTION_SUPPORT = "suggestion_support"


class ClaimVerificationVerdict(StrEnum):
    """Supported verdicts for claim-level verification results."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    MISSING_EVIDENCE = "missing_evidence"
    NEEDS_EXTERNAL_VERIFICATION = "needs_external_verification"


class ClaimSourceType(StrEnum):
    """Supported sources for candidate claims entering the verifier."""

    PLANNER_QUERY = "planner_query"
    PARSED_TEXT_FALLBACK = "parsed_text_fallback"


class ExternalCheckStatus(StrEnum):
    """Lifecycle states for claim-scoped external verification."""

    NOT_NEEDED = "not_needed"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ExternalToolName(StrEnum):
    """Supported tools for selective claim-scoped external verification."""

    SEARCH_ARXIV = "search_arxiv"
    SEARCH_SEMANTIC_SCHOLAR = "search_semantic_scholar"
    CHECK_GITHUB_REPO = "check_github_repo"


class ExternalEvidenceMatchStatus(StrEnum):
    """How confidently an external result matches the scoped claim/query."""

    MATCHED = "matched"
    PLAUSIBLE_MATCH = "plausible_match"
    AMBIGUOUS_MATCH = "ambiguous_match"
    NOT_FOUND = "not_found"
    ERROR = "error"
    UNKNOWN = "unknown"


class ExternalEvidenceImpact(StrEnum):
    """How a normalized external evidence record affects the claim."""

    SUPPORTS = "supports"
    WEAKENS = "weakens"
    UNRESOLVED = "unresolved"


class ExternalSupportStrength(StrEnum):
    """Conservative strength bucket for normalized external evidence."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    UNKNOWN = "unknown"


class ExternalResolutionStatus(StrEnum):
    """How the claim-level external merge affected the final verification."""

    NOT_APPLICABLE = "not_applicable"
    REINFORCED_INTERNAL = "reinforced_internal"
    WEAKENED_INTERNAL = "weakened_internal"
    CHANGED_VERDICT = "changed_verdict"
    STILL_UNRESOLVED = "still_unresolved"
