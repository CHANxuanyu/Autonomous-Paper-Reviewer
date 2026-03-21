# Benchmark Scaffold

This directory contains the first claim-level benchmark scaffold for the repository.

## What Exists Now

- A JSONL dataset format for paper-level claim evaluation.
- A checked-in curated benchmark slice in `benchmarks/data/curated_tool_needed_v1.jsonl`.
- A benchmark runner with five strategy names:
  `direct_long_context`, `vanilla_rag`, `dedicated_claim_verifier`,
  `tool_augmented_claim_verifier`, and `current_pipeline`.
- Initial metrics for:
  retrieval `Recall@k`,
  claim verdict accuracy,
  internal-only versus tool-needed subset accuracy,
  and latency capture.
- Reuse of the existing parser, chunker, embedder, and retriever through an in-memory retrieval path for benchmark runs.

## What Is Still Scaffolded

- `direct_long_context` is wired into the runner, but it is currently a placeholder baseline rather than a full long-context verifier.
- `vanilla_rag` remains a deterministic scaffold baseline over the richer retrieval contract.
- `dedicated_claim_verifier` is the model-backed internal-only verifier.
- `tool_augmented_claim_verifier` and `current_pipeline` use the explicit claim verification stage with selective external checks.
- The curated dataset is intentionally small and still depends on local/materialized PDF fixtures.

## Dataset Format

Use one JSON object per line:

```json
{
  "paper_id": "paper-001",
  "pdf_path": "path/to/paper.pdf",
  "focus_areas": ["novelty", "reproducibility"],
  "claims": [
    {
      "claim_text": "The method outperforms all reported baselines on ImageNet.",
      "gold_label": "supported",
      "tool_needed": true,
      "required_tool": "search_semantic_scholar",
      "external_gold_expectation": "weakens",
      "gold_external_evidence_hints": [
        "Expect prior-work search results rather than a decisive novelty confirmation."
      ],
      "gold_evidence_spans": [
        {
          "page_number": 6,
          "text": "Table 2 shows our method achieves the best top-1 accuracy...",
          "section_name": "Results"
        }
      ],
      "gold_visual_evidence": ["table_2"]
    }
  ]
}
```

Field notes:

- `tool_needed`: marks claims where internal paper evidence is expected to be insufficient on its own.
- `required_tool`: the external tool a strong tool-augmented strategy is expected to route to for that claim.
- `external_gold_expectation`: the expected effect of external evidence when annotated, such as `supports`, `weakens`, or `unresolved`.
- `gold_external_evidence_hints`: optional free-form hints for dataset authors about what external evidence should look like.

## Running

From the project root:

```bash
source .venv/bin/activate
python -m benchmarks.materialize_curated_slice
python -m benchmarks.runner --dataset path/to/claim_eval.jsonl
```

Optional flags:

```bash
python -m benchmarks.runner \
  --dataset benchmarks/data/curated_tool_needed_v1.jsonl \
  --strategies dedicated_claim_verifier tool_augmented_claim_verifier \
  --output-dir benchmarks/results
```

Credential notes:

- `direct_long_context` is still a placeholder and does not exercise parser or embedding calls.
- `vanilla_rag`, `dedicated_claim_verifier`, `tool_augmented_claim_verifier`, and `current_pipeline`
  all require the same OpenAI credentials as the main application flow because parsing/retrieval
  benchmarks still depend on embeddings and the model-backed verifier.
- `tool_augmented_claim_verifier` and `current_pipeline` additionally depend on the external
  network-accessible tools behind the local MCP server, including ArXiv, Semantic Scholar, and GitHub.

## Output

For each strategy the runner writes:

- `benchmarks/results/<strategy>_predictions.jsonl`
- `benchmarks/results/<strategy>_summary.json`

The summary now includes tool-needed benchmark slices such as:

- how many claims are annotated as tool-needed
- internal-only versus tool-needed verdict accuracy
- whether the expected tool was actually used
- how often tool-needed claims remained unresolved
- how often external checks changed or resolved a verdict

## Planned Next Steps

- Expand the curated benchmark slice beyond the current small v1 fixture set.
- Replace the `direct_long_context` placeholder with a real long-context claim verifier.
- Add stronger evidence matching and richer retrieval metrics such as MRR and nDCG.
- Add richer evaluation for external evidence quality beyond routing and resolution counts.
