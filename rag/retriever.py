"""Vector retrieval helpers for claim-to-evidence lookup."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.db import SessionLocal
from rag.embedder import embed_texts
from schemas.enums import EvidenceType

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MAX_EVIDENCES = 12
DEFAULT_TOP_K = 4
BROAD_TOP_K = 8


def _normalize_tokens(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens for simple keyword overlap."""

    return set(TOKEN_PATTERN.findall(text.lower()))


def _infer_evidence_type(text: str, key_path: tuple[str, ...]) -> str:
    """Map a review-plan item to an evidence type."""

    haystack = " ".join([*key_path, text]).lower()
    if any(token in haystack for token in ("weakness", "concern", "risk", "limitation", "missing")):
        return EvidenceType.CONCERN.value
    if any(token in haystack for token in ("suggest", "improve", "recommend")):
        return EvidenceType.SUGGESTION_SUPPORT.value
    return EvidenceType.FACT.value


def _extract_query_specs(review_plan: dict[str, Any]) -> list[dict[str, str]]:
    """Flatten a review-plan payload into retrievable claim strings."""

    extracted: list[dict[str, str]] = []

    def visit(value: Any, key_path: tuple[str, ...] = ()) -> None:
        if isinstance(value, str):
            claim = value.strip()
            if claim:
                extracted.append(
                    {
                        "claim": claim,
                        "evidence_type": _infer_evidence_type(claim, key_path),
                    }
                )
            return

        if isinstance(value, dict):
            preferred = value.get("claim") or value.get("query") or value.get("question") or value.get("aspect")
            if isinstance(preferred, str) and preferred.strip():
                claim = preferred.strip()
                extracted.append(
                    {
                        "claim": claim,
                        "evidence_type": _infer_evidence_type(claim, key_path),
                    }
                )

            for key, nested_value in value.items():
                if key in {"claim", "query", "question", "aspect"}:
                    continue
                visit(nested_value, (*key_path, str(key)))
            return

        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            for item in value:
                visit(item, key_path)

    visit(review_plan)

    deduped: OrderedDict[str, dict[str, str]] = OrderedDict()
    for item in extracted:
        deduped.setdefault(item["claim"], item)

    if deduped:
        return list(deduped.values())

    fallback_claim = json.dumps(review_plan, ensure_ascii=False)
    return [{"claim": fallback_claim, "evidence_type": EvidenceType.FACT.value}]


def _vector_distance_expression(vector_column: Any, query_embedding: list[float]) -> Any:
    """Create a cosine-distance SQL expression compatible with pgvector."""

    try:
        return vector_column.cosine_distance(query_embedding)
    except AttributeError:
        return vector_column.op("<=>")(query_embedding)


def _confidence_from_distance(distance: float, keyword_overlap: float) -> float:
    """Fuse vector similarity with lightweight keyword overlap into [0, 1]."""

    vector_similarity = max(0.0, min(1.0, 1.0 - float(distance)))
    fused_score = (0.8 * vector_similarity) + (0.2 * keyword_overlap)
    return round(max(0.0, min(1.0, fused_score)), 2)


def retrieve_evidences(
    document_id: UUID,
    review_plan: dict[str, Any],
    *,
    broaden: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve top evidence chunks for the current review plan."""

    from models.vector_chunk import VectorChunk

    query_specs = _extract_query_specs(review_plan)
    query_texts = [spec["claim"] for spec in query_specs]
    query_embeddings = embed_texts(query_texts)
    top_k = BROAD_TOP_K if broaden else DEFAULT_TOP_K

    evidence_by_key: OrderedDict[tuple[UUID, str], dict[str, Any]] = OrderedDict()
    db = SessionLocal()
    try:
        for spec, query_embedding in zip(query_specs, query_embeddings, strict=True):
            distance_expr = _vector_distance_expression(VectorChunk.embedding, query_embedding)
            stmt = (
                select(VectorChunk, distance_expr.label("distance"))
                .where(VectorChunk.document_id == document_id)
                .order_by(distance_expr.asc())
                .limit(top_k)
            )
            rows = db.execute(stmt).all()
            query_tokens = _normalize_tokens(spec["claim"])

            for chunk, distance in rows:
                chunk_tokens = _normalize_tokens(chunk.chunk_text)
                overlap = 0.0
                if query_tokens:
                    overlap = len(query_tokens & chunk_tokens) / len(query_tokens)

                candidate = {
                    "chunk_id": chunk.id,
                    "claim": spec["claim"],
                    "confidence_score": _confidence_from_distance(float(distance), overlap),
                    "evidence_type": spec["evidence_type"],
                    "linked_image_path": chunk.linked_image_path,
                }
                evidence_key = (chunk.id, spec["claim"])
                existing = evidence_by_key.get(evidence_key)
                if existing is None or candidate["confidence_score"] > existing["confidence_score"]:
                    evidence_by_key[evidence_key] = candidate

        sorted_evidences = sorted(
            evidence_by_key.values(),
            key=lambda item: item["confidence_score"],
            reverse=True,
        )
        return sorted_evidences[:MAX_EVIDENCES]
    finally:
        db.close()
