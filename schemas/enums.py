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
