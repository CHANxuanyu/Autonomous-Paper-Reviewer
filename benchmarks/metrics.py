"""Initial claim-level benchmark metrics for retrieval and verification."""

from __future__ import annotations

from typing import Any

from benchmarks.dataset import PaperBenchmarkRecord


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _claim_key(paper_id: str, claim_text: str) -> tuple[str, str]:
    return paper_id, _normalize_text(claim_text)


def retrieval_recall_at_k(
    strategy_results: list[dict[str, Any]],
    dataset_records: list[PaperBenchmarkRecord],
    *,
    k: int = 3,
) -> dict[str, Any]:
    """Compute a lightweight evidence hit-rate based Recall@k."""

    gold_by_claim = {
        _claim_key(record.paper_id, claim.claim_text): claim
        for record in dataset_records
        for claim in record.claims
    }

    hits = 0
    total = 0
    for result in strategy_results:
        paper_id = str(result.get("paper_id") or "")
        for prediction in result.get("claim_predictions") or []:
            gold_claim = gold_by_claim.get(_claim_key(paper_id, str(prediction.get("claim_text") or "")))
            if gold_claim is None or not gold_claim.gold_evidence_spans:
                continue

            total += 1
            predicted_quotes = [_normalize_text(value) for value in (prediction.get("evidence_quotes") or [])[:k]]
            predicted_pages = {
                int(page_number)
                for page_number in (prediction.get("page_numbers") or [])[:k]
                if page_number is not None
            }

            matched = False
            for gold_span in gold_claim.gold_evidence_spans:
                gold_text = _normalize_text(gold_span.text)
                if gold_text and any(gold_text in quote or quote in gold_text for quote in predicted_quotes if quote):
                    matched = True
                    break
                if gold_span.page_number is not None and int(gold_span.page_number) in predicted_pages:
                    matched = True
                    break

            if matched:
                hits += 1

    recall = round(hits / total, 4) if total else None
    return {"metric": f"retrieval_recall@{k}", "hits": hits, "total": total, "value": recall}


def claim_verdict_accuracy(
    strategy_results: list[dict[str, Any]],
    dataset_records: list[PaperBenchmarkRecord],
) -> dict[str, Any]:
    """Compute exact-match verdict accuracy against labeled benchmark claims."""

    gold_by_claim = {
        _claim_key(record.paper_id, claim.claim_text): claim.gold_label.value
        for record in dataset_records
        for claim in record.claims
    }

    correct = 0
    total = 0
    for result in strategy_results:
        paper_id = str(result.get("paper_id") or "")
        for prediction in result.get("claim_predictions") or []:
            gold_label = gold_by_claim.get(_claim_key(paper_id, str(prediction.get("claim_text") or "")))
            if gold_label is None:
                continue
            total += 1
            if str(prediction.get("predicted_verdict") or "") == gold_label:
                correct += 1

    accuracy = round(correct / total, 4) if total else None
    return {"metric": "claim_verdict_accuracy", "correct": correct, "total": total, "value": accuracy}


def claim_subset_accuracy_summary(
    strategy_results: list[dict[str, Any]],
    dataset_records: list[PaperBenchmarkRecord],
) -> dict[str, Any]:
    """Break down verdict accuracy for internal-only versus tool-needed claims."""

    gold_by_claim = {
        _claim_key(record.paper_id, claim.claim_text): claim
        for record in dataset_records
        for claim in record.claims
    }

    internal_only_total = 0
    internal_only_correct = 0
    tool_needed_total = 0
    tool_needed_correct = 0

    for result in strategy_results:
        paper_id = str(result.get("paper_id") or "")
        for prediction in result.get("claim_predictions") or []:
            gold_claim = gold_by_claim.get(_claim_key(paper_id, str(prediction.get("claim_text") or "")))
            if gold_claim is None:
                continue

            predicted_verdict = str(prediction.get("predicted_verdict") or "")
            is_correct = predicted_verdict == gold_claim.gold_label.value

            if gold_claim.tool_needed:
                tool_needed_total += 1
                if is_correct:
                    tool_needed_correct += 1
            else:
                internal_only_total += 1
                if is_correct:
                    internal_only_correct += 1

    return {
        "metric": "claim_subset_accuracy_summary",
        "internal_only_claims": internal_only_total,
        "internal_only_correct": internal_only_correct,
        "internal_only_accuracy": (
            round(internal_only_correct / internal_only_total, 4)
            if internal_only_total
            else None
        ),
        "tool_needed_claims": tool_needed_total,
        "tool_needed_correct": tool_needed_correct,
        "tool_needed_accuracy": (
            round(tool_needed_correct / tool_needed_total, 4)
            if tool_needed_total
            else None
        ),
    }


def tool_needed_claim_summary(dataset_records: list[PaperBenchmarkRecord]) -> dict[str, Any]:
    """Summarize how many benchmark claims explicitly require external tool help."""

    tool_needed_claims = 0
    required_tool_annotated = 0
    external_expectation_annotated = 0
    for record in dataset_records:
        for claim in record.claims:
            if claim.tool_needed:
                tool_needed_claims += 1
            if claim.required_tool is not None:
                required_tool_annotated += 1
            if claim.external_gold_expectation is not None:
                external_expectation_annotated += 1

    return {
        "metric": "tool_needed_claim_summary",
        "tool_needed_claims": tool_needed_claims,
        "required_tool_annotated": required_tool_annotated,
        "external_expectation_annotated": external_expectation_annotated,
    }


def required_tool_usage_summary(
    strategy_results: list[dict[str, Any]],
    dataset_records: list[PaperBenchmarkRecord],
) -> dict[str, Any]:
    """Measure whether a strategy actually used the expected tool on annotated claims."""

    gold_by_claim = {
        _claim_key(record.paper_id, claim.claim_text): claim
        for record in dataset_records
        for claim in record.claims
        if claim.required_tool is not None
    }

    expected_tool_used = 0
    total = 0
    for result in strategy_results:
        paper_id = str(result.get("paper_id") or "")
        for prediction in result.get("claim_predictions") or []:
            gold_claim = gold_by_claim.get(_claim_key(paper_id, str(prediction.get("claim_text") or "")))
            if gold_claim is None:
                continue
            total += 1
            used_tools = {str(tool_name) for tool_name in prediction.get("tools_used") or []}
            if gold_claim.required_tool and gold_claim.required_tool.value in used_tools:
                expected_tool_used += 1

    return {
        "metric": "required_tool_usage_summary",
        "expected_tool_used": expected_tool_used,
        "total": total,
        "value": round(expected_tool_used / total, 4) if total else None,
    }


def tool_needed_outcome_summary(
    strategy_results: list[dict[str, Any]],
    dataset_records: list[PaperBenchmarkRecord],
) -> dict[str, Any]:
    """Summarize resolution behavior on claims marked as tool-needed."""

    gold_by_claim = {
        _claim_key(record.paper_id, claim.claim_text): claim
        for record in dataset_records
        for claim in record.claims
        if claim.tool_needed
    }

    total = 0
    claims_with_external_checks = 0
    resolved_after_strategy = 0
    unresolved_after_strategy = 0
    verdicts_changed_by_external = 0
    correct = 0

    for result in strategy_results:
        paper_id = str(result.get("paper_id") or "")
        for prediction in result.get("claim_predictions") or []:
            gold_claim = gold_by_claim.get(_claim_key(paper_id, str(prediction.get("claim_text") or "")))
            if gold_claim is None:
                continue

            total += 1
            if int(prediction.get("external_check_count") or 0) > 0:
                claims_with_external_checks += 1
            if prediction.get("verdict_changed_by_external"):
                verdicts_changed_by_external += 1

            needs_external = bool(prediction.get("needs_external_check"))
            predicted_verdict = str(prediction.get("predicted_verdict") or "")
            if not needs_external and predicted_verdict not in {"needs_external_verification", "missing_evidence"}:
                resolved_after_strategy += 1
            else:
                unresolved_after_strategy += 1

            if predicted_verdict == gold_claim.gold_label.value:
                correct += 1

    return {
        "metric": "tool_needed_outcome_summary",
        "tool_needed_claims": total,
        "claims_with_external_checks": claims_with_external_checks,
        "resolved_after_strategy": resolved_after_strategy,
        "unresolved_after_strategy": unresolved_after_strategy,
        "verdicts_changed_by_external": verdicts_changed_by_external,
        "tool_needed_verdict_accuracy": round(correct / total, 4) if total else None,
    }


def latency_summary(strategy_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize recorded strategy latency for a benchmark run."""

    paper_latencies = [
        float(result["total_latency_ms"])
        for result in strategy_results
        if result.get("total_latency_ms") is not None
    ]
    claim_latencies = [
        float(prediction["latency_ms"])
        for result in strategy_results
        for prediction in (result.get("claim_predictions") or [])
        if prediction.get("latency_ms") is not None
    ]

    return {
        "metric": "latency_summary",
        "paper_count": len(paper_latencies),
        "claim_count": len(claim_latencies),
        "avg_paper_latency_ms": round(sum(paper_latencies) / len(paper_latencies), 2) if paper_latencies else None,
        "avg_claim_latency_ms": round(sum(claim_latencies) / len(claim_latencies), 2) if claim_latencies else None,
    }


def external_check_summary(strategy_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize how often claims were flagged for and resolved with external checks."""

    total_claims = 0
    claims_requiring_external_check = 0
    claims_with_external_checks = 0
    verdicts_changed_by_external = 0
    external_latency_values: list[float] = []

    for result in strategy_results:
        for prediction in result.get("claim_predictions") or []:
            total_claims += 1
            if prediction.get("needs_external_check"):
                claims_requiring_external_check += 1
            if int(prediction.get("external_check_count") or 0) > 0:
                claims_with_external_checks += 1
            if prediction.get("verdict_changed_by_external"):
                verdicts_changed_by_external += 1
            if prediction.get("external_latency_ms") is not None:
                external_latency_values.append(float(prediction["external_latency_ms"]))

    return {
        "metric": "external_check_summary",
        "claim_count": total_claims,
        "claims_requiring_external_check": claims_requiring_external_check,
        "claims_with_external_checks": claims_with_external_checks,
        "verdicts_changed_by_external": verdicts_changed_by_external,
        "external_check_rate": round(claims_with_external_checks / total_claims, 4) if total_claims else None,
        "avg_external_latency_ms": (
            round(sum(external_latency_values) / len(external_latency_values), 2)
            if external_latency_values
            else None
        ),
    }
