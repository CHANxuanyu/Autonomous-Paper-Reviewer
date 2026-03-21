"""Vector retrieval helpers for claim-to-evidence lookup."""

from __future__ import annotations

import json
import math
import re
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.db import SessionLocal
from rag.embedder import embed_texts
from schemas.enums import EvidenceType
from schemas.retrieval import RetrievedEvidenceSchema

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
MAX_EVIDENCES = 12
DEFAULT_TOP_K = 4
BROAD_TOP_K = 8
MAX_SEARCH_KEYWORDS = 6


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


def _extract_query_specs(review_plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer claim-centric query items from the structured review plan."""

    queries = review_plan.get("queries")
    extracted: list[dict[str, Any]] = []

    if isinstance(queries, Iterable) and not isinstance(queries, (str, bytes, bytearray, dict)):
        for item in queries:
            if not isinstance(item, dict):
                continue

            claim = str(item.get("claim") or item.get("query") or item.get("question") or "").strip()
            if not claim:
                continue

            search_keywords = [
                str(keyword).strip()
                for keyword in (item.get("search_keywords") or [])
                if str(keyword).strip()
            ][:MAX_SEARCH_KEYWORDS]
            aspect = str(item.get("aspect") or "").strip() or None

            priority: int | None = None
            try:
                raw_priority = item.get("priority")
                if raw_priority is not None:
                    priority = int(raw_priority)
            except (TypeError, ValueError):
                priority = None

            extracted.append(
                {
                    "claim": claim,
                    "query_text": claim,
                    "search_keywords": search_keywords,
                    "aspect": aspect,
                    "priority": priority,
                    "evidence_type": _infer_evidence_type(claim, ("queries", aspect or "")),
                }
            )

    deduped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for item in sorted(extracted, key=lambda value: (value.get("priority") or 999, value["claim"])):
        deduped.setdefault(item["claim"], item)

    if deduped:
        return list(deduped.values())

    fallback_claim = str(review_plan.get("plan_summary") or "").strip()
    if not fallback_claim:
        fallback_claim = json.dumps(review_plan, ensure_ascii=False)

    return [
        {
            "claim": fallback_claim,
            "query_text": fallback_claim,
            "search_keywords": [],
            "aspect": None,
            "priority": None,
            "evidence_type": EvidenceType.FACT.value,
        }
    ]


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


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    """Compute cosine distance for in-memory benchmark retrieval."""

    if len(left) != len(right):
        raise ValueError("Embeddings must have matching dimensionality.")

    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 1.0

    similarity = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    similarity = max(-1.0, min(1.0, similarity))
    return 1.0 - similarity


def _query_tokens_for_spec(spec: dict[str, Any]) -> set[str]:
    """Build lightweight lexical features from the primary claim plus optional keywords."""

    tokens = _normalize_tokens(str(spec.get("claim") or ""))
    for keyword in spec.get("search_keywords") or []:
        tokens.update(_normalize_tokens(str(keyword)))
    return tokens


def _chunk_payload_from_db_chunk(chunk: Any) -> dict[str, Any]:
    """Normalize a database chunk row into the shared retrieval payload shape."""

    return {
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "chunk_text": chunk.chunk_text,
        "page_number": chunk.page_number,
        "section_name": chunk.section_name,
        "chunk_index": chunk.chunk_index,
        "linked_image_path": chunk.linked_image_path,
    }


def _chunk_payload_from_memory_chunk(chunk: dict[str, Any], index: int) -> dict[str, Any]:
    """Normalize an in-memory chunk payload into the shared retrieval payload shape."""

    chunk_id = chunk.get("chunk_id")
    if chunk_id is None:
        chunk_id = f"chunk-{chunk.get('chunk_index', index)}"

    return {
        "chunk_id": chunk_id,
        "document_id": None,
        "chunk_text": str(chunk.get("chunk_text") or ""),
        "page_number": chunk.get("page_number"),
        "section_name": chunk.get("section_name"),
        "chunk_index": chunk.get("chunk_index"),
        "linked_image_path": chunk.get("linked_image_path"),
    }


def _build_retrieved_evidence(
    *,
    spec: dict[str, Any],
    chunk_payload: dict[str, Any],
    distance: float,
    keyword_overlap: float,
    retrieval_rank: int,
    retrieval_source: str,
) -> dict[str, Any]:
    """Assemble and validate the rich evidence contract shared by production and benchmarks."""

    confidence_score = _confidence_from_distance(distance, keyword_overlap)
    evidence = RetrievedEvidenceSchema(
        chunk_id=chunk_payload["chunk_id"],
        document_id=chunk_payload.get("document_id"),
        claim=spec["claim"],
        query_text=str(spec.get("query_text") or spec["claim"]),
        aspect=spec.get("aspect"),
        priority=spec.get("priority"),
        evidence_type=spec["evidence_type"],
        confidence_score=confidence_score,
        score=confidence_score,
        vector_distance=round(float(distance), 4),
        keyword_overlap=round(float(keyword_overlap), 4),
        retrieval_rank=retrieval_rank,
        retrieval_source=retrieval_source,
        chunk_text=chunk_payload["chunk_text"],
        page_number=chunk_payload.get("page_number"),
        section_name=chunk_payload.get("section_name"),
        chunk_index=chunk_payload.get("chunk_index"),
        linked_image_path=chunk_payload.get("linked_image_path"),
    )
    return evidence.model_dump()


def retrieve_evidences(
    document_id: UUID,
    review_plan: dict[str, Any],
    *,
    broaden: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve top evidence chunks for the current review plan."""

    from models.vector_chunk import VectorChunk

    query_specs = _extract_query_specs(review_plan)
    query_texts = [str(spec.get("query_text") or spec["claim"]) for spec in query_specs]
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
            query_tokens = _query_tokens_for_spec(spec)

            for retrieval_rank, (chunk, distance) in enumerate(rows, start=1):
                chunk_payload = _chunk_payload_from_db_chunk(chunk)
                chunk_tokens = _normalize_tokens(chunk_payload["chunk_text"])
                overlap = 0.0
                if query_tokens:
                    overlap = len(query_tokens & chunk_tokens) / len(query_tokens)

                candidate = _build_retrieved_evidence(
                    spec=spec,
                    chunk_payload=chunk_payload,
                    distance=float(distance),
                    keyword_overlap=overlap,
                    retrieval_rank=retrieval_rank,
                    retrieval_source="pgvector",
                )
                evidence_key = (str(chunk.id), spec["claim"])
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


def retrieve_evidences_from_chunks(
    chunks: Sequence[dict[str, Any]],
    chunk_embeddings: Sequence[Sequence[float]],
    review_plan: dict[str, Any],
    *,
    broaden: bool = False,
) -> list[dict[str, Any]]:
    """Run the same claim-centric retrieval contract directly on in-memory chunks."""

    if len(chunks) != len(chunk_embeddings):
        raise ValueError("chunks and chunk_embeddings must have the same length")

    query_specs = _extract_query_specs(review_plan)
    query_texts = [str(spec.get("query_text") or spec["claim"]) for spec in query_specs]
    query_embeddings = embed_texts(query_texts)
    top_k = BROAD_TOP_K if broaden else DEFAULT_TOP_K

    evidence_by_key: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
    normalized_chunks = [
        _chunk_payload_from_memory_chunk(chunk, index)
        for index, chunk in enumerate(chunks)
    ]

    for spec, query_embedding in zip(query_specs, query_embeddings, strict=True):
        query_tokens = _query_tokens_for_spec(spec)
        scored_chunks: list[tuple[dict[str, Any], float]] = []
        for chunk_payload, chunk_embedding in zip(normalized_chunks, chunk_embeddings, strict=True):
            scored_chunks.append((chunk_payload, _cosine_distance(query_embedding, chunk_embedding)))

        top_rows = sorted(scored_chunks, key=lambda item: item[1])[:top_k]
        for retrieval_rank, (chunk_payload, distance) in enumerate(top_rows, start=1):
            chunk_tokens = _normalize_tokens(chunk_payload["chunk_text"])
            overlap = 0.0
            if query_tokens:
                overlap = len(query_tokens & chunk_tokens) / len(query_tokens)

            candidate = _build_retrieved_evidence(
                spec=spec,
                chunk_payload=chunk_payload,
                distance=distance,
                keyword_overlap=overlap,
                retrieval_rank=retrieval_rank,
                retrieval_source="in_memory",
            )
            evidence_key = (str(chunk_payload["chunk_id"]), spec["claim"])
            existing = evidence_by_key.get(evidence_key)
            if existing is None or candidate["confidence_score"] > existing["confidence_score"]:
                evidence_by_key[evidence_key] = candidate

    sorted_evidences = sorted(
        evidence_by_key.values(),
        key=lambda item: item["confidence_score"],
        reverse=True,
    )
    return sorted_evidences[:MAX_EVIDENCES]
