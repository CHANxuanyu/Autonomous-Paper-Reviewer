"""Standalone MCP server exposing local academic reviewer tools over stdio."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from urllib import parse, request
from urllib.error import URLError

from mcp.server.fastmcp import FastMCP

from tools.arxiv_search import search_arxiv as _search_arxiv
from tools.github_check import check_github_repo as _check_github_repo

mcp = FastMCP("AcademicReviewerTools")


@mcp.tool()
def search_arxiv(query: str, max_results: int = 3) -> str:
    """Search ArXiv for related work or novelty verification.

    Args:
        query: Search query derived from the academic paper under review.
        max_results: Maximum number of ArXiv matches to summarize.

    Returns:
        A natural-language summary of the top ArXiv matches, or a graceful
        fallback message when the lookup cannot be completed.
    """

    return _search_arxiv(query=query, max_results=max_results)


@mcp.tool()
def search_semantic_scholar(query: str, limit: int = 3) -> str:
    """Search Semantic Scholar for academic papers and citation metadata.

    Args:
        query: Search query derived from the academic paper under review.
        limit: Maximum number of matching papers to summarize.

    Returns:
        A readable summary of matching papers across the broader Semantic
        Scholar academic graph, including citation counts and URLs, or a
        graceful fallback message if the external API fails.
    """

    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return "Semantic Scholar search skipped because no query was provided."

    safe_limit = max(1, min(limit, 5))
    encoded_query = parse.quote(normalized_query)
    api_url = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={encoded_query}&limit={safe_limit}"
        "&fields=title,authors,year,citationCount,influentialCitationCount,url"
    )
    api_request = request.Request(
        api_url,
        headers={"User-Agent": "Academic-Paper-Analyzer-Agent/1.0"},
    )

    try:
        with request.urlopen(api_request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        return (
            f"Semantic Scholar search failed due to network error ({exc}). "
            "Please rely solely on the provided internal PDF context."
        )
    except json.JSONDecodeError as exc:
        return (
            f"Semantic Scholar search failed due to invalid JSON response ({exc}). "
            "Please rely solely on the provided internal PDF context."
        )
    except Exception as exc:
        return (
            f"Semantic Scholar search failed due to unexpected API error ({exc}). "
            "Please rely solely on the provided internal PDF context."
        )

    papers = payload.get("data") or []
    if not papers:
        return f"No Semantic Scholar results found for query '{normalized_query}'."

    lines = [f"Semantic Scholar results for query: {normalized_query}"]
    for paper in papers:
        title = str(paper.get("title") or "Untitled")
        year = str(paper.get("year") or "Unknown year")
        authors = paper.get("authors") or []
        author_names = ", ".join(
            str(author.get("name") or "").strip() for author in authors if str(author.get("name") or "").strip()
        ) or "Unknown authors"
        citation_count = int(paper.get("citationCount") or 0)
        influential_citation_count = int(paper.get("influentialCitationCount") or 0)
        paper_url = str(paper.get("url") or "No URL available")
        lines.append(
            "- "
            f"{title} ({year}) by {author_names}. "
            f"Citations: {citation_count} (Influential: {influential_citation_count}). "
            f"URL: {paper_url}"
        )

    return "\n".join(lines)


@mcp.tool()
def check_github_repo(repo_url: str) -> str:
    """Check the authenticity and health of a GitHub repository.

    Args:
        repo_url: Public GitHub repository URL cited by the paper authors.

    Returns:
        A natural-language assessment of repository availability, maintenance
        signals, and code reproducibility health, or a graceful fallback
        message if the external check fails.
    """

    return _check_github_repo(repo_url=repo_url)


@mcp.tool()
def execute_python_code(code: str) -> str:
    """Execute isolated Python code and return its output or error details.

    Args:
        code: Python source code to execute in a temporary isolated script.
            Make sure to print() any values or results you want returned to the
            model.

    Returns:
        The standard output produced by the script, an execution error message,
        or a graceful timeout/runtime failure string.
    """

    temp_file_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
            temp_file.write(code)
            temp_file_path = temp_file.name

        result = subprocess.run(
            [sys.executable, temp_file_path],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            stdout = result.stdout.strip()
            if stdout:
                return stdout
            return "Execution completed successfully, but no stdout was produced. Use print() to expose results."

        stderr = result.stderr.strip() or "Unknown execution failure."
        return f"Execution Error:\n{stderr}"
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out after 10 seconds. Check for infinite loops."
    except Exception as exc:
        return f"Error: Python code execution failed gracefully ({exc})."
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)


if __name__ == "__main__":
    mcp.run()
