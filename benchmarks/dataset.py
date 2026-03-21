"""Dataset models and loading helpers for claim-level paper benchmarks."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from schemas.enums import ClaimVerificationVerdict, ExternalEvidenceImpact, ExternalToolName


class GoldEvidenceSpan(BaseModel):
    """One gold evidence reference for a benchmark claim."""

    model_config = ConfigDict(from_attributes=True)

    page_number: int | None = None
    text: str
    section_name: str | None = None


class ClaimBenchmarkItem(BaseModel):
    """One labeled claim to evaluate for a paper."""

    model_config = ConfigDict(from_attributes=True)

    claim_text: str
    gold_label: ClaimVerificationVerdict
    gold_evidence_spans: list[GoldEvidenceSpan] = Field(default_factory=list)
    gold_visual_evidence: list[str] = Field(default_factory=list)
    tool_needed: bool = False
    required_tool: ExternalToolName | None = None
    external_gold_expectation: ExternalEvidenceImpact | None = None
    gold_external_evidence_hints: list[str] = Field(default_factory=list)


class PaperBenchmarkRecord(BaseModel):
    """One paper-level benchmark record stored as a JSONL row."""

    model_config = ConfigDict(from_attributes=True)

    paper_id: str
    pdf_path: str
    focus_areas: list[str] = Field(default_factory=list)
    claims: list[ClaimBenchmarkItem] = Field(default_factory=list)


def load_dataset(dataset_path: str | Path) -> list[PaperBenchmarkRecord]:
    """Load a JSONL benchmark dataset from disk."""

    path = Path(dataset_path)
    records: list[PaperBenchmarkRecord] = []
    with path.open("r", encoding="utf-8") as dataset_file:
        for line_number, line in enumerate(dataset_file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            try:
                records.append(PaperBenchmarkRecord.model_validate(payload))
            except Exception as exc:
                raise ValueError(f"Invalid benchmark record on line {line_number}: {exc}") from exc
    return records
