# Technical Architecture Document
## Academic Paper Analyzer

**System Classification:** Agentic Multimodal Academic Peer-Review Pipeline

---

## 1. Executive Summary & System Objectives

Academic Paper Analyzer is an **agentic, asynchronous, multimodal academic peer-review pipeline** designed to transform a static PDF into a stateful review process grounded in evidence, external literature, code availability signals, and controlled computational verification.

The system is not architected as a single synchronous “LLM call wrapped in an API.” Instead, it deliberately separates:

- ingress and orchestration,
- persistent workflow state,
- multimodal retrieval,
- agent planning and reasoning,
- external tool execution,
- and user-facing observability.

At a high level, the platform performs the following sequence:

1. Accept a paper upload through a FastAPI boundary.
2. Persist document metadata and enqueue a long-running review task.
3. Parse the PDF into text blocks and visual assets.
4. Convert the document into semantically retrievable vector chunks while preserving cross-modal bindings.
5. Use a Planner Agent to construct a retrieval-oriented review plan.
6. Use a Reviewer Agent to retrieve evidence, invoke external tools through MCP, and produce a schema-constrained peer-review report.
7. Surface the state machine and final outputs through Streamlit in a way that reduces the “LLM black box” effect.

### Primary Objectives

| Objective | Architectural Interpretation |
| --- | --- |
| Evidence-grounded review generation | Every major judgement should be traceable to retrieved chunks, visual anchors, or external references |
| Decoupled long-running execution | Heavy parsing, embedding, and reasoning must not block the request/response API surface |
| Multimodal context fidelity | Figures and tables must remain attached to nearby semantics rather than being treated as disconnected binary artifacts |
| Tool modularity | External lookups and computation should be callable without hard-coding tool logic into the reasoning loop |
| Operational robustness | Tool failures, quota failures, and partial retries should degrade semantically rather than collapsing the pipeline |
| Interview-grade architecture clarity | The codebase should expose strong patterns in state management, idempotency, isolation, and structured outputs |

---

## 2. High-Level Distributed Architecture

The current implementation is a **locally deployable distributed system** built from loosely coupled runtime roles:

- **FastAPI** as the ingress and polling layer
- **Celery + Redis** as the asynchronous execution fabric
- **PostgreSQL + pgvector** as both transactional state store and retrieval substrate
- **Streamlit** as a semantic operations console for users
- **MCP over stdio** as the tool-execution boundary between reasoning and side effects

### 2.1 Topology Overview

```mermaid
flowchart LR
    UI[Streamlit UI] -->|POST /documents| API[FastAPI]
    UI -->|POST /reviews| API
    UI -->|GET /reviews/{task_id}| API

    API --> DB[(PostgreSQL + pgvector)]
    API -->|delay(task_id)| CELERY[Celery Worker]
    CELERY --> REDIS[(Redis broker/backend)]
    CELERY --> DB
    CELERY --> OPENAI[OpenAI Responses API]
    CELERY --> MCP[MCP stdio tool server]
    MCP --> EXT1[ArXiv API]
    MCP --> EXT2[Semantic Scholar API]
    MCP --> EXT3[GitHub REST API]
    MCP --> PY[Python sandbox subprocess]
```

### 2.2 Role of Each Runtime

| Component | Responsibility | Notable Implementation Detail |
| --- | --- | --- |
| FastAPI | Thin API boundary for upload, task creation, and polling | Async route functions wrapping synchronous SQLAlchemy sessions |
| Celery Worker | Long-lived workflow executor | Multi-stage FSM, explicit retries, fatal-error fail-fast branches |
| Redis | Broker and result backend | JSON task serialization, UTC task tracking |
| PostgreSQL | Durable system-of-record | Stores documents, review tasks, evidences, JSON results, timestamps |
| pgvector | Retrieval substrate | Stores 1536-d embeddings on `vector_chunks.embedding` |
| Streamlit | Human-facing orchestration and result rendering | Long-polls the FSM every 2 seconds and renders structured outputs |
| MCP Server | Tool runtime boundary | Decouples reviewer reasoning from network calls and code execution |

### 2.3 Request-to-Completion Sequence

1. `POST /api/v1/documents`
   - Stores the uploaded PDF under `uploads/`.
   - Creates a `documents` row with status `UPLOADED`.
2. `POST /api/v1/reviews`
   - Performs a pre-flight OpenAI API key check.
   - Creates a `review_tasks` row with status `PENDING`.
   - Enqueues `run_review_task.delay(task_id)`.
3. Celery Worker
   - Advances the FSM from parsing through reporting.
   - Persists checkpoints after every major state transition.
4. `GET /api/v1/reviews/{task_id}`
   - Returns status, retry count, timestamps, failure reason, and final `result_json`.
5. Streamlit
   - Polls until terminal status.
   - Renders the structured report, external references, and code reproducibility section.

### 2.4 Deployment Character

The code is currently optimized for a **single-node local deployment topology**:

- PostgreSQL defaults to `localhost:5432`
- Redis defaults to `localhost:6379`
- Celery and FastAPI are launched from the same project root

This is not a weakness in architectural shape. The seams for production hardening already exist:

- isolated worker role,
- externalized broker,
- database-backed FSM,
- MCP-based tool decoupling,
- and strict schema boundaries between components.

---

## 3. Advanced Context Management & Memory Architecture

This section is the architectural core of the system.

The pipeline maintains **three different classes of context** at the same time:

1. **Working memory** inside the active reasoning loop
2. **Persistent memory** across asynchronous boundaries
3. **Cross-modal bindings** that preserve semantic relationships between text and visual evidence

### 3.1 Working Memory: Prompt-State, Tool State, and Message Trajectories

The Reviewer Agent constructs its working memory dynamically rather than relying on a monolithic prompt string.

#### Core Working-Memory Artifacts

| Artifact | Scope | Purpose |
| --- | --- | --- |
| `review_prompt` | Current review transaction | Consolidates title, metadata, abstract, plan, and compacted evidences |
| `content` blocks | Current model call | Mixes `input_text` with `input_image` blocks for multimodal reasoning |
| `previous_response_id` | Responses API conversation state | Allows the final structured-output call to continue the same reasoning thread |
| `tool_outputs` | Reasoning phase only | Holds structured `function_call_output` messages fed back into the model |
| `system_prompt` | Entire reviewer session | Encodes behavioral rules for tool use, evidence discipline, and output schema expectations |

#### Multimodal Working Memory Construction

The Reviewer builds content blocks with `_build_multimodal_user_content(...)`, which:

- starts with a textual review payload,
- resolves local `linked_image_path` values,
- base64-encodes images,
- injects them into the model request as separate multimodal inputs.

Conceptually, the memory object looks like:

```python
[
    {"role": "system", "content": system_prompt},
    {
        "role": "user",
        "content": [
            {"type": "input_text", "text": review_prompt},
            {"type": "input_image", "image_url": "data:image/png;base64,..."},
            {"type": "input_image", "image_url": "data:image/png;base64,..."},
        ],
    },
]
```

This is important because the system does not merely “store images in the database.” It explicitly **replays them into the LLM’s active context window** at reasoning time.

#### Tool-Trajectory Memory

The reasoning loop in `_run_reasoning_and_tools(...)` uses a two-stage pattern:

1. initial model call with tool schemas,
2. tool execution,
3. replay of tool results as `function_call_output`,
4. final schema-constrained generation.

That means the reasoning loop preserves:

- tool name,
- tool arguments,
- tool output,
- and prior model state (`previous_response_id`)

inside the same logical conversation.

This is the working-memory equivalent of a **micro ReAct trace**.

### 3.2 Persistent Memory: FSM as Durable Cognitive State

The real system memory is not the prompt. It is the database.

The `review_tasks` table acts as a **durable finite-state machine** preserving global context across decoupled processes. This is the architectural move that allows a thin API layer and a separate worker to behave like one coherent system.

#### Durable FSM States

| State | Meaning |
| --- | --- |
| `PENDING` | Accepted but not yet processed |
| `PARSING_DOC` | PDF structure and metadata extraction |
| `VECTORIZING` | Chunk generation, embedding, vector persistence |
| `AGENT_PLANNING` | Planner Agent generating retrieval intent |
| `EVIDENCE_RETRIEVAL` | Chunk recall from pgvector |
| `REPORT_GENERATING` | Reviewer Agent performing multimodal/tool reasoning |
| `COMPLETED` | Result JSON and evidences persisted |
| `FAILED` | Terminal fault state |

#### Why This Matters

Without persistent task state, an LLM pipeline is just a volatile function call.  
With it, the system gains:

- retry semantics,
- failure resumability,
- auditable transitions,
- timestamped lifecycle control,
- and UI-readable progress.

#### Persistence Surfaces

| Table | Memory Function |
| --- | --- |
| `documents` | Physical artifact metadata and parse/index lifecycle |
| `review_tasks` | Global workflow state, structured output, retry count, failure context |
| `vector_chunks` | Long-lived semantic memory derived from the document |
| `evidences` | Claim-to-chunk lineage connecting judgments to retrieval results |

### 3.3 Cross-Modal Context Binding: Semantic Anchoring of Visual Evidence

The most architecturally interesting retrieval feature in the codebase is not just multimodal parsing, but **how visual evidence is bound back to text context**.

#### Parsing Stage

`rag/parser.py` uses Unstructured in `hi_res` mode with:

- `infer_table_structure=True`
- `extract_image_block_types=["Image", "Table"]`

The parser emits:

- ordered `text_blocks`
- ordered `visual_blocks`
- per-document media directories under `media/documents/{document_id}/images`

Each visual block carries:

- `order`
- `category`
- `image_path`
- `caption_or_context`
- `anchor_text_order`

#### Chunking Stage

`rag/chunker.py` then constructs a token-level anchoring model:

1. every text block gets a token span,
2. page token windows are generated,
3. each visual anchor is mapped onto text span end positions,
4. distance to each chunk window is computed using half-open intervals `[start, end)`,
5. the closest chunk is selected,
6. if no valid anchor exists, a synthetic visual chunk is created.

Key implementation features:

- `_distance_to_window(position, start, end)` uses half-open interval semantics
- missing anchor spans no longer default to `0`
- orphan visuals generate independent synthetic chunks instead of being pinned to the page header

This matters because it prevents a serious multimodal corruption pattern:

- image extracted correctly,
- text indexed correctly,
- but image semantically attached to the wrong chunk.

The `linked_image_path` field on `vector_chunks` becomes the durable bridge between modalities.

### 3.4 Contextual Graceful Degradation

A particularly strong design pattern in the codebase is **semantic degradation instead of hard failure propagation**.

Tool failures are intentionally converted into language that the model can reason about.

Examples:

- ArXiv network/parsing failures return a natural-language fallback string
- GitHub API failures return `Tool Error: ... Please rely solely on the provided internal PDF context.`
- MCP call failures return `Tool Error: MCP execution failed for ...`
- Python sandbox timeouts return explicit timeout guidance instead of blowing up the worker

This is context management, not just exception handling.

The effect is that infrastructure faults become **reasoning-visible context**, rather than silent collapse of the chain-of-thought pipeline.

---

## 4. Model Context Protocol (MCP) & Tool Orchestration

The project has evolved from local in-process tools toward **protocolized tool execution** using MCP over `stdio`.

### 4.1 Why MCP Matters Here

Without MCP, tools are ordinary Python function calls tightly coupled to the reviewer module.  
With MCP, the architecture cleanly separates:

- agent cognition,
- tool schema declaration,
- tool process lifecycle,
- and side-effecting execution.

In this repository:

- `mcp_server.py` exposes tools with `FastMCP`
- `agents/reviewer.py` acts as an MCP client via `stdio_client(...)` and `ClientSession(...)`
- the Reviewer still retains explicit tool JSON schemas for stable LLM-facing interface control

This is a practical hybrid:

- **MCP for execution decoupling**
- **local schema definitions for deterministic model contract stability**

### 4.2 MCP over stdio

The execution path is:

```python
server_params = StdioServerParameters(
    command=sys.executable,
    args=[os.path.join(PROJECT_ROOT, "mcp_server.py")],
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool(function_name, arguments)
```

This gives the system several advantages:

- tool runtime is isolated from reviewer business logic,
- tool calls are protocolized rather than direct imports,
- the reviewer can stay agnostic to implementation details of each tool,
- future remote or containerized tool servers become possible without redesigning the prompt contract.

### 4.3 Tool Catalog

| Tool | Domain | Primary Use |
| --- | --- | --- |
| `search_arxiv` | External literature | Recent preprints, novelty checks, emerging related work |
| `search_semantic_scholar` | External literature graph | Citation counts, influential works, broad scholarly coverage |
| `check_github_repo` | Software artifact verification | Public code authenticity, maintenance signals, reproducibility |
| `execute_python_code` | Controlled computation | Formula validation, statistical sanity checks, algorithm logic verification |

### 4.4 Quantitative Tool Outputs as Structured Signals

The Semantic Scholar path is especially interesting because it returns not just prose, but quantitative metadata:

- `citationCount`
- `influentialCitationCount`

Those values are intentionally reflected in:

- the MCP tool output text,
- the reviewer system prompt,
- and the Pydantic output schema (`ExternalReferenceSchema`)

This allows the model to convert tool text into structured review artifacts without a separate parser layer.

### 4.5 Operational Note

The codebase already contains the MCP server/client integration.  
Operationally, the runtime environment must ensure the `mcp` package is installed in the execution environment, even though the present dependency manifest does not yet pin it explicitly.

That is not a conceptual architecture gap; it is a deployment-packaging detail.

---

## 5. Security, Isolation & Sandboxing

The `execute_python_code` MCP tool introduces the highest-risk surface in the platform: **LLM-generated code execution**.

The current implementation mitigates this risk through a layered sandboxing strategy.

### 5.1 Execution Boundary

The tool does not use `exec()` inside the MCP server process.  
Instead, it:

1. writes code to a temporary `.py` file,
2. launches a separate Python subprocess,
3. captures stdout/stderr,
4. enforces a hard timeout,
5. deletes the temp file in a `finally` block.

Relevant shape:

```python
with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
    temp_file.write(code)
    temp_file_path = temp_file.name

result = subprocess.run(
    [sys.executable, temp_file_path],
    capture_output=True,
    text=True,
    timeout=10,
)
```

### 5.2 Mitigation Model

| Risk | Mitigation in Current Code | Effect |
| --- | --- | --- |
| Infinite loops | `timeout=10` and explicit `TimeoutExpired` handling | Prevents unbounded execution time |
| File persistence | Ephemeral temp file + `finally: os.remove(...)` | Minimizes disk residue |
| Parent-process corruption | Execution in a child subprocess | Prevents direct contamination of MCP server interpreter state |
| Silent failure | stderr/stdout captured and returned semantically | Converts execution failures into reviewer-visible context |

### 5.3 Security Boundary Honesty

From an architecture-review perspective, precision matters:

- this **is** a meaningful execution boundary,
- but it is **not yet** equivalent to container-level, VM-level, seccomp, gVisor, or syscall-filter sandboxing.

What the current design guarantees:

- process isolation from the parent interpreter,
- temporal bounding,
- ephemeral file handling,
- graceful error propagation.

What it does not yet guarantee:

- resource quotas beyond time,
- filesystem jail semantics,
- network egress restrictions,
- kernel-level isolation.

That distinction is important, and calling it out is a sign of architectural maturity rather than weakness.

---

## 6. Idempotency, Consistency & Concurrency

### 6.1 Idempotency

The worker is built around the assumption that **retries will happen**.

That is why idempotency is not an afterthought. It is explicitly coded into the pipeline.

#### Vectorization Retry Hygiene

If a failure occurs during `VECTORIZING`, the worker calls:

- `cleanup_vector_chunks(db, document_id=...)`

before retrying.

This prevents:

- duplicate chunk insertion,
- mixed-version embeddings,
- retrieval pollution,
- downstream evidence inconsistency.

#### Fail-Fast vs Retryable Faults

The worker distinguishes between retryable and fatal faults:

| Failure Class | Behavior |
| --- | --- |
| `openai.AuthenticationError` | Immediate terminal failure |
| `openai.RateLimitError` with `insufficient_quota` | Immediate terminal failure |
| generic exceptions during stages | rollback, retry count increment, stage-aware backoff |

This distinction fixes an important class of asynchronous bug: configuration or quota failures should not masquerade as transient transport faults.

### 6.2 ACID-Oriented Session Discipline

`core/db.py` configures SQLAlchemy with:

```python
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)
```

The consequences are meaningful:

- transactions are explicit,
- object state is not immediately invalidated after commit,
- worker code can refresh intentionally,
- rollback boundaries remain legible.

FastAPI and Celery do **not** share a global ambient session. Instead:

- API requests receive a request-scoped session via `get_db()`
- workers create their own isolated session via `get_worker_session()`

This reduces the risk of:

- dirty session reuse,
- stale object access across boundaries,
- and hidden transaction bleed-through.

### 6.3 Concurrency Model

The system handles concurrency by **moving heavyweight work out of the API path**.

FastAPI’s role is intentionally narrow:

- validate request,
- persist minimal state,
- enqueue task,
- return immediately.

All expensive operations happen in Celery:

- PDF partitioning,
- OCR-heavy multimodal extraction,
- embedding generation,
- vector retrieval,
- LLM reasoning,
- external API access,
- MCP tool orchestration.

This means the FastAPI layer remains responsive even while the worker is saturated with:

- long OpenAI calls,
- rate-limited external APIs,
- or expensive multimodal processing.

### 6.4 Backoff Strategy

Retries are not uniform:

- `VECTORIZING` uses exponential backoff (`2 ** retry_count`)
- other stages use linear retry countdown

This is a pragmatic choice because vectorization is the most expensive stage and the one most likely to benefit from cooling down before retry.

---

## 7. Observability & Agentic Tracing

A strong system is not just correct; it is inspectable.

### 7.1 FSM-Level Observability

The Streamlit UI polls `GET /api/v1/reviews/{task_id}` every 2 seconds and surfaces:

- current FSM stage,
- retry count,
- error messages,
- document/task identifiers,
- progress bars,
- terminal success/failure state.

This creates a user-visible execution trace of the asynchronous workflow.

### 7.2 Semantic Trace Surfaces

The current implementation does not persist full raw MCP frames or full tool-argument logs as a dedicated tracing subsystem.  
Instead, it surfaces **semantic traces**:

- external references checked,
- code reproducibility assessment,
- evidence-backed strengths/weaknesses,
- missing evidence warnings,
- and state-machine progression.

This is still highly valuable because it reveals **why** a conclusion was reached, even if it is not yet a full OpenTelemetry-style trace stack.

### 7.3 Structured Internal Trace Artifacts

Internally, the reviewer does maintain structured tool artifacts:

- model-emitted `function_call`
- parsed JSON arguments
- `function_call_output`
- `previous_response_id`

These artifacts are not just logs; they are part of the reasoning trajectory itself.

### 7.4 UI as an Explainability Surface

The UI is intentionally designed to make the pipeline legible:

- state timeline cards explain the current stage,
- result tabs separate summaries from weaknesses and follow-up questions,
- external-reference cards surface literature lookups,
- code reproducibility panels surface GitHub/tool-based code-health conclusions.

This is an architectural choice to make an agentic system inspectable without exposing raw chain-of-thought.

---

## 8. Multi-Agent Loop & Structured Outputs

The system uses a deliberate **Planner -> Retriever -> Reviewer** decomposition.

### 8.1 Planner Agent

The Planner produces a retrieval-oriented plan via `ReviewPlanSchema`.

That plan includes:

- review aspects,
- claims to verify,
- rationales,
- search keywords,
- priorities.

This is not ornamental planning. It converts an open-ended peer-review problem into a set of retrievable evidence objectives.

### 8.2 Reviewer Agent

The Reviewer consumes:

- parsed document metadata,
- abstract or first-page excerpt,
- retrieved chunk evidence,
- linked visual context,
- external tool outputs from MCP,
- and the prior reasoning trajectory.

It then emits a structured `ReviewResultSchema`.

### 8.3 Schema-Constrained Outputs

The output contract is enforced via Pydantic and OpenAI structured outputs.

Current result structure includes:

| Field | Purpose |
| --- | --- |
| `summary` | High-level reviewer synthesis |
| `strengths` | Concrete positive findings |
| `weaknesses` | Concrete negative findings |
| `missing_evidence` | Claims that could not be adequately verified |
| `questions_for_authors` | Clarifying questions that materially affect confidence |
| `code_reproducibility_check` | Structured commentary on code availability and repository health |
| `external_references_checked` | Structured related-work artifacts, optionally with citation metrics |

`external_references_checked` is particularly powerful because it bridges tool outputs back into a stable schema with fields such as:

- `title`
- `authors`
- `published_date`
- `summary`
- `citation_count`
- `influential_citation_count`

This means the LLM is not only allowed to reason about outside data, but also required to **normalize it into a deterministic contract**.

### 8.4 Why This Matters Architecturally

Structured outputs provide three enterprise-grade properties:

1. **Stability**  
   The frontend and API layer do not depend on brittle prose parsing.

2. **Auditability**  
   Every major semantic output class has a named field.

3. **Extensibility**  
   New capabilities such as citation analytics or code-health assessment can be added by extending schemas rather than rewriting UI contracts.

---

## Closing Assessment

Academic Paper Analyzer is best understood not as a “paper summary app,” but as a **stateful, tool-augmented, multimodal review system** whose architecture intentionally combines:

- asynchronous orchestration,
- durable workflow memory,
- multimodal semantic anchoring,
- protocolized tool execution,
- sandboxed computation,
- structured outputs,
- and human-readable observability.

That combination is precisely what makes the system compelling to senior engineers and interviewers: it demonstrates not just model integration, but **system design under uncertainty, failure, and cross-modal complexity**.
