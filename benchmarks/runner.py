"""CLI runner for the benchmark scaffolding introduced in milestone 1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.dataset import load_dataset
from benchmarks.metrics import (
    claim_subset_accuracy_summary,
    claim_verdict_accuracy,
    external_check_summary,
    latency_summary,
    retrieval_recall_at_k,
    required_tool_usage_summary,
    tool_needed_claim_summary,
    tool_needed_outcome_summary,
)
from benchmarks.strategies import PaperStrategyResult, StrategyName, run_strategy


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run claim-level benchmark strategies.")
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to a JSONL benchmark dataset.",
    )
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=[strategy.value for strategy in StrategyName],
        choices=[strategy.value for strategy in StrategyName],
        help="One or more strategy names to execute.",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmarks/results",
        help="Directory where JSONL predictions and summary metrics will be written.",
    )
    return parser.parse_args()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as output_file:
        for row in rows:
            output_file.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    args = _parse_args()
    dataset_records = load_dataset(args.dataset)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for strategy_name in args.strategies:
        strategy = StrategyName(strategy_name)
        strategy_results: list[PaperStrategyResult] = []

        for record in dataset_records:
            try:
                result = run_strategy(strategy, record)
            except Exception as exc:
                result = PaperStrategyResult(
                    paper_id=record.paper_id,
                    strategy=strategy,
                    total_latency_ms=0.0,
                    claim_predictions=[],
                    error_message=str(exc),
                )
            strategy_results.append(result)

        serialized_results = [result.model_dump(mode="json") for result in strategy_results]
        metrics = {
            "strategy": strategy.value,
            "dataset_path": str(args.dataset),
            "record_count": len(dataset_records),
            "metrics": [
                retrieval_recall_at_k(serialized_results, dataset_records, k=3),
                claim_verdict_accuracy(serialized_results, dataset_records),
                claim_subset_accuracy_summary(serialized_results, dataset_records),
                tool_needed_claim_summary(dataset_records),
                required_tool_usage_summary(serialized_results, dataset_records),
                tool_needed_outcome_summary(serialized_results, dataset_records),
                external_check_summary(serialized_results),
                latency_summary(serialized_results),
            ],
        }

        result_path = output_dir / f"{strategy.value}_predictions.jsonl"
        summary_path = output_dir / f"{strategy.value}_summary.json"
        _write_jsonl(result_path, serialized_results)
        summary_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"Wrote {strategy.value} predictions to {result_path}")
        print(f"Wrote {strategy.value} summary to {summary_path}")


if __name__ == "__main__":
    main()
