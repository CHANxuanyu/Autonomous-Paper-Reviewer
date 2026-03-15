# 🦄 Autonomous AI Paper Reviewer

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688.svg)
![Celery](https://img.shields.io/badge/Celery-5.3%2B-37814A.svg)
![pgvector](https://img.shields.io/badge/pgvector-Supported-336791.svg)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991.svg)

An enterprise-grade, multi-agent system that autonomously reviews academic papers. Moving beyond standard text-based RAG, this system implements **Multimodal Vision RAG**, real-time **ArXiv fact-checking**, and an **Asynchronous Event-Driven Architecture** to deliver expert-level, hallucination-free academic feedback.

## ✨ 📸 See It In Action

*(Replace these placeholder links with your actual awesome UI screenshots)*

![Dashboard Overview](https://via.placeholder.com/800x400.png?text=Modern+Streamlit+Dashboard+Screenshot)
*The modern, playful UI featuring live status polling and a tabbed report view.*

![Vision RAG & Fact Checking](https://via.placeholder.com/800x400.png?text=ArXiv+Fact+Checking+Cards+Screenshot)
*Agentic fact-checking: The system autonomously queries ArXiv to cross-validate authors' claims.*

## 🚀 Core Features

* 👁️ **Multimodal Vision RAG**: Utilizes `Unstructured` (hi-res strategy) to parse PDFs, isolating not just text, but accurately extracting and anchoring **Figures and Tables**. Feeds base64-encoded images to GPT-4o for authentic "visual" peer review.
* 🕵️‍♂️ **Agentic Fact-Checking (Tool Calling)**: Employs the ReAct paradigm. The Reviewer Agent dynamically invokes an external `search_arxiv` tool to verify novelty and identify missing baseline comparisons in real-time.
* ⚡ **Asynchronous & Decoupled Backend**: Built on **FastAPI** with **Celery + Redis** task queues. Safely offloads long-running LLM reasoning and heavy document vectorization, ensuring a non-blocking, highly responsive client experience.
* 🗄️ **Robust Vector Retrieval**: Backed by **PostgreSQL & pgvector**, enabling hybrid retrieval strategies with exact source-citation to eliminate LLM hallucinations.
* 🛡️ **Strict Structured Outputs**: Leverages Pydantic and OpenAI's strict structured output schema to guarantee 100% deterministic JSON report formats (Summary, Strengths, Weaknesses, Questions).
* 🎨 **Polished UX/UI**: A beautiful Streamlit frontend featuring custom CSS, intuitive sidebar controls, immersive loading states, and elegant tabbed data presentation.

## 🧠 Architecture Overview

1.  **Ingestion**: User uploads a PDF. FastAPI delegates the heavy lifting to a Celery worker.
2.  **Multimodal Parsing**: The PDF is chunked. Images/Tables are extracted, saved locally, and linked to the nearest semantic text chunk in PostgreSQL via pgvector.
3.  **Planning Phase**: A Planner Agent extracts metadata and constructs a targeted retrieval strategy.
4.  **Reasoning Phase (Tool Use)**: The Reviewer Agent retrieves vector chunks + linked images. It decides whether to search ArXiv to verify claims.
5.  **Generation**: Using GPT-4o, it synthesizes the internal PDF context with external ArXiv references into a strict JSON schema.
6.  **Polling**: The Streamlit UI polls FastAPI, updating the user with engaging UI state changes until the final balloons 🎈 drop.

## 🛠️ Getting Started

### Prerequisites
* Python 3.12+
* PostgreSQL (with `pgvector` extension)
* Redis (running on `localhost:6379`)
* OpenAI API Key (with GPT-4o access)

### Installation

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/YOUR_USERNAME/Autonomous-Paper-Reviewer.git](https://github.com/YOUR_USERNAME/Autonomous-Paper-Reviewer.git)
   cd Autonomous-Paper-Reviewer
   ```
