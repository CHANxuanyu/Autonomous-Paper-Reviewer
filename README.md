# Academic Paper Analyzer

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Async%20API-009688?logo=fastapi&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-Distributed%20Workers-37814A?logo=celery&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-Responses%20API-412991)
![MCP](https://img.shields.io/badge/MCP-Tool%20Orchestration-5B5BD6)
![Streamlit](https://img.shields.io/badge/Streamlit-Interactive%20UI-FF4B4B?logo=streamlit&logoColor=white)

Academic Paper Analyzer is a **stateful, evidence-grounded, claim-centric, tool-augmented academic paper due-diligence system**. It turns a PDF into an asynchronous verification workflow that parses multimodal content, retrieves auditable evidence, verifies claims against internal paper evidence, selectively augments unresolved claims with external tools, and persists both low-level verification artifacts and high-level review synthesis.

This repository is designed to showcase modern AI systems engineering rather than prompt wiring alone. It combines **FastAPI**, **Celery**, **PostgreSQL + pgvector**, **OpenAI multimodal reasoning**, **MCP-based tool execution**, and **Streamlit** into a system that is inspectable, benchmarkable, and explicit about uncertainty.

> For the full architecture document, read [TECHNICAL_ARCHITECTURE_EN.md](TECHNICAL_ARCHITECTURE_EN.md).

## What The System Does

- Accepts a paper PDF and runs it through a durable asynchronous workflow rather than a single blocking request.
- Parses text, figures, and tables from the document and preserves cross-modal anchors between visuals and nearby text.
- Builds retrievable chunk memory with provenance such as chunk text, page number, section, score, and linked visual context.
- Runs a dedicated `CLAIM_VERIFICATION` stage that evaluates candidate claims against internal paper evidence.
- Uses external tools only when justified, with deterministic claim-scoped routing for GitHub, Semantic Scholar, and arXiv.
- Normalizes external tool outputs into typed external evidence records instead of treating them as loose text blobs.
- Persists structured review output together with claim-level audit artifacts that can be inspected in the UI or benchmarked offline.

## Why This Is Not Just A Summary App

This project is not centered on “upload PDF -> get summary.”

What makes it different:

- **Claim-level adjudication**: important judgments exist as explicit claim verification objects, not only as prose.
- **Evidence lineage**: verdicts can carry chunk IDs, quotes, pages, sections, and linked visual context.
- **Internal vs external evidence separation**: the system distinguishes what the paper itself supports from what external tools suggest.
- **Selective tool augmentation**: tools are used for flagged claims, not as a blanket search layer.
- **Conservative unresolved handling**: novelty and prior-work claims can remain unresolved when evidence is weak.
- **Benchmark support**: the repo includes claim-level benchmark strategies and a curated tool-needed evaluation slice.

## Key Capabilities

- **Async workflow with durable state**: review tasks move through a database-backed FSM from upload through parsing, retrieval, claim verification, and report generation.
- **Multimodal parsing and visual anchoring**: extracted figures and tables are linked back to nearby text chunks rather than treated as detached assets.
- **Claim-centric verification**: a dedicated `CLAIM_VERIFICATION` stage verifies candidate claims before final review synthesis.
- **Evidence-grounded retrieval**: downstream reasoning consumes rich evidence objects, not just chunk IDs.
- **Selective external checks**: GitHub is used for code/reproducibility claims, Semantic Scholar for literature/comparison claims, and arXiv as a novelty/prior-work signal.
- **Typed external evidence**: tool outputs are normalized into structured evidence records with provenance and support/weakening signals.
- **Structured outputs**: final results include both high-level review fields and low-level `claim_verifications`.
- **Explainable UI**: Streamlit exposes claim verdicts, quotes, page numbers, tools used, external-check status, and typed external evidence summaries.
- **Benchmark framework**: the repo supports internal-only and tool-augmented claim-verifier strategies.
- **Curated benchmark slice**: a small manually curated dataset exercises internal-only and tool-needed claims for regression-style evaluation.

## Workflow Overview

At a high level, the implemented pipeline is:

```text
Upload PDF
-> parse text + visuals
-> chunk + embed + persist retrieval memory
-> planner builds retrieval-oriented review intent and claim candidates
-> retrieve internal evidence
-> dedicated claim verification
-> selective external checks for flagged claims
-> typed external evidence normalization
-> review synthesis
-> structured persistence + UI inspection
```

The worker executes this as a durable asynchronous workflow, with a first-class `CLAIM_VERIFICATION` stage between retrieval and report generation.

For the full state-machine, memory, and contract details, see [TECHNICAL_ARCHITECTURE_EN.md](TECHNICAL_ARCHITECTURE_EN.md).

## System Snapshot

| Layer | Responsibility |
| --- | --- |
| FastAPI | Upload boundary, task creation, polling endpoints, evidence inspection |
| Celery + Redis | Asynchronous execution and retry orchestration |
| PostgreSQL + pgvector | Workflow state, retrieval memory, evidence persistence |
| Planner Agent | Retrieval-oriented review intent and claim candidate generation |
| Claim Verifier | Internal-first claim adjudication and selective external verification |
| Reviewer Agent | High-level synthesis over claim-verification artifacts |
| MCP Server | External research tools and bounded code execution |
| Streamlit | Live workflow visibility and claim-level result inspection |
| Benchmark Runner | Offline strategy comparison over labeled claim datasets |

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/CHANxuanyu/Academic_Paper_Analyzer.git
cd Academic_Paper_Analyzer
```

### 2. Create the virtual environment and install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt streamlit requests mcp
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=sk-your-key-here
```

Current local infrastructure defaults in code:

- PostgreSQL: `postgresql+psycopg://user:pass@localhost:5432/paper_db`
- Redis: `redis://localhost:6379/0`

### 4. Start PostgreSQL and Redis

```bash
docker compose up -d
```

### 5. Bootstrap the local runtime

This installs OCR/system packages required by multimodal parsing, installs Python dependencies, and applies the lightweight DB migration used by the vision pipeline.

```bash
./start_servers.sh --bootstrap
```

### 6. Start the API and Celery worker

```bash
./start_servers.sh --background
```

### 7. Launch the Streamlit UI

```bash
source .venv/bin/activate
streamlit run app.py
```

Then open:

- API docs: `http://127.0.0.1:8000/docs`
- Streamlit UI: `http://localhost:8501`

## Benchmark Support

The repository includes a benchmark framework under `benchmarks/` with strategy variants such as:

- `dedicated_claim_verifier` for internal-only claim verification
- `tool_augmented_claim_verifier` for internal-first verification plus selective external checks
- scaffold baselines such as `direct_long_context` and `vanilla_rag`

It also includes a small curated benchmark slice for tool-needed claims:

- checked-in annotations: `benchmarks/data/curated_tool_needed_v1.jsonl`
- source/fixture manifest: `benchmarks/data/curated_tool_needed_v1_sources.json`
- PDF materialization helper: `python -m benchmarks.materialize_curated_slice`

Example benchmark commands:

```bash
source .venv/bin/activate
python -m benchmarks.materialize_curated_slice
python -m benchmarks.runner \
  --dataset benchmarks/data/curated_tool_needed_v1.jsonl \
  --strategies dedicated_claim_verifier tool_augmented_claim_verifier \
  --output-dir benchmarks/results
```

Benchmark caveats:

- the current benchmark is a curated v1 slice, not a large-scale corpus
- tool-augmented strategies require credentials and network/tool access
- one benchmark fixture may still require local/manual PDF placement if automated retrieval is blocked

## Repository Guide

Important files and docs:

- [TECHNICAL_ARCHITECTURE_EN.md](TECHNICAL_ARCHITECTURE_EN.md): detailed architecture document
- [benchmarks/README.md](benchmarks/README.md): benchmark framework overview
- [benchmarks/data/README.md](benchmarks/data/README.md): curated benchmark slice details
- `main.py`: FastAPI application entrypoint
- `workers/review_tasks.py`: async workflow entrypoint and durable FSM execution
- `app.py`: Streamlit UI and claim/result inspection surface
- `mcp_server.py`: MCP tool server

## Current Boundaries

The current implementation is intentionally stronger than a summary pipeline, but it still has clear boundaries:

- novelty verification is conservative and signal-oriented rather than a full literature-graph proof system
- claim verifications are persisted explicitly in `result_json`, not yet in a dedicated normalized relational table
- literature matching is useful for routing and weak challenge/support signals, but still conservative
- the benchmark is a curated regression-oriented slice rather than a broad benchmark suite
- bounded Python subprocess execution exists, but it is not a hardened isolation environment

## Further Reading

- [TECHNICAL_ARCHITECTURE_EN.md](TECHNICAL_ARCHITECTURE_EN.md)
- [benchmarks/README.md](benchmarks/README.md)
- [benchmarks/data/README.md](benchmarks/data/README.md)
