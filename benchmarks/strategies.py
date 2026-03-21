"""Strategy scaffolding for claim-level benchmark experiments."""

from __future__ import annotations

from enum import Enum
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agents import claim_verifier, orchestrator
from benchmarks.dataset import PaperBenchmarkRecord
from rag import chunker, embedder, parser, retriever
from schemas.enums import ClaimVerificationVerdict


class StrategyName(str, Enum):
    """Benchmark strategies wired into the v1 runner."""

    DIRECT_LONG_CONTEXT = "direct_long_context"
    VANILLA_RAG = "vanilla_rag"
    DEDICATED_CLAIM_VERIFIER = "dedicated_claim_verifier"
    TOOL_AUGMENTED_CLAIM_VERIFIER = "tool_augmented_claim_verifier"
    CURRENT_PIPELINE = "current_pipeline"


class ClaimPredictionSchema(BaseModel):
    """Claim-level prediction emitted by a benchmark strategy."""

    model_config = ConfigDict(from_attributes=True)

    claim_text: str
    predicted_verdict: ClaimVerificationVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    claim_source: str | None = None
    internal_verdict: ClaimVerificationVerdict | None = None
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    section_names: list[str] = Field(default_factory=list)
    linked_image_paths: list[str] = Field(default_factory=list)
    needs_external_check: bool = False
    external_check_reason: str | None = None
    external_verification_status: str | None = None
    external_resolution_status: str | None = None
    external_check_count: int = Field(ge=0, default=0)
    external_evidence_count: int = Field(ge=0, default=0)
    tools_used: list[str] = Field(default_factory=list)
    external_source_urls: list[str] = Field(default_factory=list)
    external_check_summary: str | None = None
    verdict_change_reason: str | None = None
    verdict_changed_by_external: bool = False
    external_evidence_records: list[dict[str, Any]] = Field(default_factory=list)
    internal_latency_ms: float | None = Field(default=None, ge=0.0)
    external_latency_ms: float | None = Field(default=None, ge=0.0)
    latency_ms: float = Field(ge=0.0)
    notes: str | None = None


class PaperStrategyResult(BaseModel):
    """One strategy run over one paper benchmark record."""

    model_config = ConfigDict(from_attributes=True)

    paper_id: str
    strategy: StrategyName
    total_latency_ms: float = Field(ge=0.0)
    claim_predictions: list[ClaimPredictionSchema] = Field(default_factory=list)
    claim_verification_summary: dict[str, Any] | None = None
    error_message: str | None = None


def _benchmark_claim_plan(
    record: PaperBenchmarkRecord,
    *,
    base_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a claim-aligned retrieval plan for benchmark evaluation."""

    return {
        "plan_summary": str(
            (base_plan or {}).get("plan_summary")
            or f"Benchmark claim verification plan for {record.paper_id}"
        ),
        "focus_areas": list((base_plan or {}).get("focus_areas") or record.focus_areas),
        "queries": [
            {
                "aspect": "claim_verification",
                "claim": claim.claim_text,
                "rationale": "Benchmark-labeled claim to verify against the paper.",
                "search_keywords": [],
                "priority": index,
            }
            for index, claim in enumerate(record.claims, start=1)
        ],
    }


def _predictions_from_claim_verifications(
    claim_verifications: list[dict[str, Any]],
    *,
    total_latency_ms: float,
) -> list[ClaimPredictionSchema]:
    """Convert structured claim verifications into benchmark prediction rows."""

    claim_count = max(len(claim_verifications), 1)
    claim_latency_ms = round(total_latency_ms / claim_count, 2)
    predictions: list[ClaimPredictionSchema] = []
    for verification in claim_verifications:
        predictions.append(
            ClaimPredictionSchema(
                claim_text=str(verification.get("claim_text") or ""),
                predicted_verdict=ClaimVerificationVerdict(str(verification.get("verdict") or ClaimVerificationVerdict.MISSING_EVIDENCE.value)),
                confidence=float(verification.get("confidence") or 0.0),
                claim_source=str(verification.get("claim_source") or "") or None,
                internal_verdict=(
                    ClaimVerificationVerdict(str(verification.get("internal_verdict")))
                    if verification.get("internal_verdict")
                    else None
                ),
                evidence_chunk_ids=[str(value) for value in verification.get("evidence_chunk_ids") or []],
                evidence_quotes=[str(value) for value in verification.get("evidence_quotes") or []],
                page_numbers=[
                    int(value)
                    for value in verification.get("page_numbers") or []
                    if value is not None
                ],
                section_names=[str(value) for value in verification.get("section_names") or []],
                linked_image_paths=[str(value) for value in verification.get("linked_image_paths") or []],
                needs_external_check=bool(verification.get("needs_external_check")),
                external_check_reason=str(verification.get("external_check_reason") or "") or None,
                external_verification_status=str(verification.get("external_verification_status") or "") or None,
                external_resolution_status=str(verification.get("external_resolution_status") or "") or None,
                external_check_count=len(verification.get("external_checks_run") or []),
                external_evidence_count=len(verification.get("external_evidence_records") or []),
                tools_used=[
                    str(check.get("tool_name"))
                    for check in verification.get("external_checks_run") or []
                    if check.get("tool_name")
                ],
                external_source_urls=[str(value) for value in verification.get("external_source_urls") or []],
                external_check_summary=str(verification.get("external_check_summary") or "") or None,
                verdict_change_reason=str(verification.get("verdict_change_reason") or "") or None,
                verdict_changed_by_external=bool(verification.get("verdict_changed_by_external")),
                external_evidence_records=[
                    dict(record)
                    for record in verification.get("external_evidence_records") or []
                    if isinstance(record, dict)
                ],
                internal_latency_ms=(
                    float(verification.get("internal_latency_ms"))
                    if verification.get("internal_latency_ms") is not None
                    else None
                ),
                external_latency_ms=(
                    float(verification.get("external_latency_ms"))
                    if verification.get("external_latency_ms") is not None
                    else None
                ),
                latency_ms=claim_latency_ms,
                notes=str(verification.get("notes") or "") or None,
            )
        )
    return predictions


def _prepare_retrieval_inputs(
    record: PaperBenchmarkRecord,
    *,
    review_plan: dict[str, Any],
    parsed_document: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[list[float]], list[dict[str, Any]]]:
    """Parse the paper and produce in-memory retrieval inputs reused across strategies."""

    if parsed_document is None:
        parsed_document = parser.parse_pdf(record.pdf_path, document_id=record.paper_id)
    chunks = chunker.split_document(parsed_document)
    chunk_embeddings = embedder.embed_chunks(chunks)
    evidences = retriever.retrieve_evidences_from_chunks(chunks, chunk_embeddings, review_plan, broaden=False)
    return parsed_document, chunks, chunk_embeddings, evidences


def run_direct_long_context(record: PaperBenchmarkRecord) -> PaperStrategyResult:
    """Placeholder baseline for future direct long-context verification experiments."""

    started_at = perf_counter()
    claim_verifications = [
        {
            "claim_text": claim.claim_text,
            "verdict": ClaimVerificationVerdict.MISSING_EVIDENCE.value,
            "confidence": 0.0,
            "evidence_chunk_ids": [],
            "evidence_quotes": [],
            "page_numbers": [],
            "section_names": [],
            "needs_external_check": False,
            "notes": (
                "Scaffold only: direct_long_context is wired into the benchmark runner, "
                "but model-based long-context claim verification is not implemented in this milestone."
            ),
        }
        for claim in record.claims
    ]
    total_latency_ms = round((perf_counter() - started_at) * 1000, 2)

    return PaperStrategyResult(
        paper_id=record.paper_id,
        strategy=StrategyName.DIRECT_LONG_CONTEXT,
        total_latency_ms=total_latency_ms,
        claim_predictions=_predictions_from_claim_verifications(
            claim_verifications,
            total_latency_ms=total_latency_ms,
        ),
        claim_verification_summary={
            "total_claims": len(record.claims),
            "claims_needing_external_check": 0,
            "claims_with_external_checks": 0,
            "external_checks_run": 0,
            "internal_latency_ms": total_latency_ms,
            "external_latency_ms": 0.0,
        },
    )


def run_vanilla_rag(record: PaperBenchmarkRecord) -> PaperStrategyResult:
    """Use the deterministic scaffold as a baseline over claim-focused retrieval."""

    started_at = perf_counter()
    review_plan = _benchmark_claim_plan(record)
    parsed_document, _, _, evidences = _prepare_retrieval_inputs(
        record,
        review_plan=review_plan,
    )
    claim_verifications = claim_verifier.build_claim_verification_scaffold(
        review_plan,
        evidences,
        parsed_document=parsed_document,
        max_claims=max(len(record.claims), 1),
    )
    total_latency_ms = round((perf_counter() - started_at) * 1000, 2)

    return PaperStrategyResult(
        paper_id=record.paper_id,
        strategy=StrategyName.VANILLA_RAG,
        total_latency_ms=total_latency_ms,
        claim_predictions=_predictions_from_claim_verifications(
            claim_verifications,
            total_latency_ms=total_latency_ms,
        ),
        claim_verification_summary={
            "total_claims": len(claim_verifications),
            "claims_needing_external_check": sum(1 for item in claim_verifications if item.get("needs_external_check")),
            "claims_with_external_checks": 0,
            "external_checks_run": 0,
            "internal_latency_ms": total_latency_ms,
            "external_latency_ms": 0.0,
        },
    )


def run_dedicated_claim_verifier(record: PaperBenchmarkRecord) -> PaperStrategyResult:
    """Run the dedicated claim verification stage directly over benchmark claims."""

    started_at = perf_counter()
    review_plan = _benchmark_claim_plan(record)
    parsed_document, chunks, chunk_embeddings, evidences = _prepare_retrieval_inputs(
        record,
        review_plan=review_plan,
    )
    verification_result = claim_verifier.verify_claims_from_chunks(
        parsed_document=parsed_document,
        review_plan=review_plan,
        chunks=chunks,
        chunk_embeddings=chunk_embeddings,
        evidences=evidences,
        max_claims=max(len(record.claims), 1),
        enable_external_checks=False,
    )
    claim_verifications = list(verification_result.get("claim_verifications") or [])
    claim_verification_summary = verification_result.get("claim_verification_summary")
    total_latency_ms = round((perf_counter() - started_at) * 1000, 2)

    return PaperStrategyResult(
        paper_id=record.paper_id,
        strategy=StrategyName.DEDICATED_CLAIM_VERIFIER,
        total_latency_ms=total_latency_ms,
        claim_predictions=_predictions_from_claim_verifications(
            claim_verifications,
            total_latency_ms=total_latency_ms,
        ),
        claim_verification_summary=claim_verification_summary,
    )


def run_tool_augmented_claim_verifier(record: PaperBenchmarkRecord) -> PaperStrategyResult:
    """Run the dedicated claim verification stage with selective external checks enabled."""

    started_at = perf_counter()
    review_plan = _benchmark_claim_plan(record)
    parsed_document, chunks, chunk_embeddings, evidences = _prepare_retrieval_inputs(
        record,
        review_plan=review_plan,
    )
    verification_result = claim_verifier.verify_claims_from_chunks(
        parsed_document=parsed_document,
        review_plan=review_plan,
        chunks=chunks,
        chunk_embeddings=chunk_embeddings,
        evidences=evidences,
        max_claims=max(len(record.claims), 1),
        enable_external_checks=True,
    )
    claim_verifications = list(verification_result.get("claim_verifications") or [])
    claim_verification_summary = verification_result.get("claim_verification_summary")
    total_latency_ms = round((perf_counter() - started_at) * 1000, 2)

    return PaperStrategyResult(
        paper_id=record.paper_id,
        strategy=StrategyName.TOOL_AUGMENTED_CLAIM_VERIFIER,
        total_latency_ms=total_latency_ms,
        claim_predictions=_predictions_from_claim_verifications(
            claim_verifications,
            total_latency_ms=total_latency_ms,
        ),
        claim_verification_summary=claim_verification_summary,
    )


def run_current_pipeline(record: PaperBenchmarkRecord) -> PaperStrategyResult:
    """Reuse planner context, then run the dedicated claim verification stage."""

    started_at = perf_counter()
    planner_note: str | None = None
    base_plan: dict[str, Any] | None = None
    parsed_document: dict[str, Any] | None = None

    try:
        parsed_document = parser.parse_pdf(record.pdf_path, document_id=record.paper_id)
        base_plan = orchestrator.plan_review(record.focus_areas, parsed_document)
    except Exception as exc:
        planner_note = f"Planner unavailable during benchmark run; fell back to benchmark claim plan ({exc})."

    review_plan = _benchmark_claim_plan(record, base_plan=base_plan)
    parsed_document, chunks, chunk_embeddings, evidences = _prepare_retrieval_inputs(
        record,
        review_plan=review_plan,
        parsed_document=parsed_document,
    )
    verification_result = claim_verifier.verify_claims_from_chunks(
        parsed_document=parsed_document,
        review_plan=review_plan,
        chunks=chunks,
        chunk_embeddings=chunk_embeddings,
        evidences=evidences,
        max_claims=max(len(record.claims), 1),
        enable_external_checks=True,
    )
    claim_verifications = list(verification_result.get("claim_verifications") or [])
    claim_verification_summary = verification_result.get("claim_verification_summary")
    total_latency_ms = round((perf_counter() - started_at) * 1000, 2)

    result = PaperStrategyResult(
        paper_id=record.paper_id,
        strategy=StrategyName.CURRENT_PIPELINE,
        total_latency_ms=total_latency_ms,
        claim_predictions=_predictions_from_claim_verifications(
            claim_verifications,
            total_latency_ms=total_latency_ms,
        ),
        claim_verification_summary=claim_verification_summary,
    )

    if planner_note and result.claim_predictions:
        for prediction in result.claim_predictions:
            combined_note = planner_note
            if prediction.notes:
                combined_note = f"{prediction.notes} {planner_note}"
            prediction.notes = combined_note

    return result


def run_strategy(strategy: StrategyName, record: PaperBenchmarkRecord) -> PaperStrategyResult:
    """Dispatch a benchmark record to the selected strategy."""

    if strategy == StrategyName.DIRECT_LONG_CONTEXT:
        return run_direct_long_context(record)
    if strategy == StrategyName.VANILLA_RAG:
        return run_vanilla_rag(record)
    if strategy == StrategyName.DEDICATED_CLAIM_VERIFIER:
        return run_dedicated_claim_verifier(record)
    if strategy == StrategyName.TOOL_AUGMENTED_CLAIM_VERIFIER:
        return run_tool_augmented_claim_verifier(record)
    if strategy == StrategyName.CURRENT_PIPELINE:
        return run_current_pipeline(record)
    raise ValueError(f"Unsupported benchmark strategy: {strategy}")
