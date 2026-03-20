# Academic Paper Analyzer

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-Async%20API-009688?logo=fastapi&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-Distributed%20Workers-37814A?logo=celery&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991)
![MCP](https://img.shields.io/badge/MCP-Tool%20Orchestration-5B5BD6)
![Streamlit](https://img.shields.io/badge/Streamlit-Interactive%20UI-FF4B4B?logo=streamlit&logoColor=white)

An **agentic multimodal academic peer-review system** that turns a paper PDF into an asynchronous, evidence-grounded review pipeline. Instead of treating peer review as a single prompt, this project combines **FastAPI**, **Celery**, **PostgreSQL + pgvector**, **OpenAI multimodal reasoning**, and the **Model Context Protocol (MCP)** to parse documents, retrieve semantic evidence, inspect charts and tables, call external research tools, and produce structured review reports.

This repository is designed to showcase modern AI systems engineering rather than just prompt wiring. It demonstrates **multimodal RAG**, **persistent workflow state**, **tool-augmented agent loops**, and **sandboxed verification**, all surfaced through a polished Streamlit interface.

> For a deep dive into the system's memory design, FSM, and MCP integration, please read the [Technical Architecture Whitepaper](TECHNICAL_ARCHITECTURE_EN.md).

## Why It Stands Out

- **Multimodal Vision Anchoring**: Parses PDFs with high-resolution structural extraction, isolates figures and tables, and binds them to the nearest semantic text chunks via token-distance anchoring.
- **MCP-Driven Tool Orchestration**: The Reviewer Agent can route external validation through MCP tools such as `search_arxiv`, `search_semantic_scholar`, and `check_github_repo`.
- **Autonomous Math Verification**: A sandboxed `execute_python_code` tool lets the agent write and run short Python programs to verify formulas, statistics, and algorithm logic.
- **Persistent Memory via PostgreSQL FSM**: Long-running review tasks survive asynchronous boundaries through a durable state machine spanning `PENDING` to `COMPLETED`/`FAILED`.
- **Asynchronous, Non-Blocking Backend**: Heavy parsing, embedding, retrieval, and reasoning are offloaded to Celery workers so the API layer stays responsive.
- **Structured, Explainable Outputs**: Final reviews are enforced through Pydantic schemas and rendered in Streamlit with external references, code-health summaries, and live workflow progress.

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

This installs the OCR/system packages required by multimodal parsing, installs Python dependencies, and applies the lightweight DB migration used by the vision pipeline.

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

## System Snapshot

| Layer | Responsibility |
| --- | --- |
| FastAPI | Upload boundary, task creation, polling endpoints |
| Celery + Redis | Asynchronous execution and retry orchestration |
| PostgreSQL + pgvector | Task state, durable memory, semantic retrieval |
| Reviewer Agent | Multimodal reasoning, MCP tool use, structured review generation |
| MCP Server | External research tools and sandboxed code execution |
| Streamlit | Live workflow visibility and polished result rendering |

## Deep Dive

The repository includes a full technical whitepaper covering:

- asynchronous finite-state orchestration
- multimodal context binding and visual anchoring
- MCP client/server tool execution
- sandbox isolation for autonomous code verification
- idempotency, retries, and graceful degradation patterns

Read it here: [TECHNICAL_ARCHITECTURE_EN.md](TECHNICAL_ARCHITECTURE_EN.md)
