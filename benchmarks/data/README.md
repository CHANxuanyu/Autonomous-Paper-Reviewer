# Curated Benchmark Slice

This directory contains a small manually curated benchmark slice for claim-level paper evaluation.

## What This Slice Is

- A v1 regression and evaluation slice, not a large-scale benchmark.
- Three papers with thirteen curated claims.
- A deliberate mix of internal-only claims, GitHub-needed claims, and literature-needed claims.
- A small amount of known ambiguity by design, so the benchmark can reward conservative behavior instead of only easy resolutions.

## Files

- `curated_tool_needed_v1.jsonl`: claim annotations consumed directly by the benchmark runner.
- `curated_tool_needed_v1_sources.json`: paper source manifest used by the PDF materialization helper.
- `pdfs/`: target directory where the local PDF fixtures should live after materialization.

## Selection Criteria

The slice was chosen to exercise the project's current strengths and current limits:

- One paper with an explicit GitHub URL and both narrow and broad reproducibility claims.
- Multiple strong novelty or state-of-the-art claims that should trigger external literature checks.
- Several straightforward internal-only claims that should be verifiable from paper evidence alone.
- At least some cases where the right answer is to remain unresolved instead of forcing an external conclusion.

## Claim Categories

- `internal_only`: claims that can reasonably be judged from the paper itself.
- `github_needed`: claims where repository reachability or basic repository health should matter.
- `literature_needed`: novelty, first-to, and state-of-the-art style claims where external lookup is justified.

## Important Limitations

- This slice is intentionally small. It is useful for demos, spot checks, and regression testing, but it is not statistically broad.
- Most literature-needed claims are labeled conservatively as `needs_external_verification`, because the current tool stack provides signals rather than definitive novelty adjudication.
- One paper currently relies on a local/manual fixture path if automated public PDF retrieval is blocked by the publisher landing page.

## Materializing The PDFs

From the project root:

```bash
source .venv/bin/activate
python -m benchmarks.materialize_curated_slice
```

The helper will:

- download public PDFs when a stable download URL is available
- otherwise copy from known local fixture candidates if they exist
- otherwise tell you which PDF path still needs to be placed manually

## Running The Curated Slice

Internal-only reference:

```bash
python -m benchmarks.runner \
  --dataset benchmarks/data/curated_tool_needed_v1.jsonl \
  --strategies dedicated_claim_verifier
```

Tool-augmented comparison:

```bash
python -m benchmarks.runner \
  --dataset benchmarks/data/curated_tool_needed_v1.jsonl \
  --strategies dedicated_claim_verifier tool_augmented_claim_verifier
```

## How To Interpret Results

- Use overall verdict accuracy as a coarse signal only.
- Pay close attention to the tool-needed summaries and required-tool usage metrics.
- Treat unresolved outputs on novelty-heavy claims as potentially correct behavior when external evidence remains weak.
- Compare internal-only and tool-augmented runs claim-by-claim before drawing conclusions from small-sample averages.
