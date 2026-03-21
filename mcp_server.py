"""Standalone MCP server exposing local academic reviewer tools over stdio."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from mcp.server.fastmcp import FastMCP

from tools.arxiv_search import search_arxiv as _search_arxiv
from tools.github_check import check_github_repo as _check_github_repo
from tools.semantic_scholar_search import search_semantic_scholar as _search_semantic_scholar

mcp = FastMCP("AcademicReviewerTools")


@mcp.tool()
def search_arxiv(query: str, max_results: int = 3) -> str:
    """Search ArXiv for related work or novelty verification.

    Args:
        query: Search query derived from the academic paper under review.
        max_results: Maximum number of ArXiv matches to summarize.

    Returns:
        A JSON string containing normalized ArXiv search results, or a graceful
        fallback payload when the lookup cannot be completed.
    """

    return _search_arxiv(query=query, max_results=max_results)


@mcp.tool()
def search_semantic_scholar(query: str, limit: int = 3) -> str:
    """Search Semantic Scholar for academic papers and citation metadata.

    Args:
        query: Search query derived from the academic paper under review.
        limit: Maximum number of matching papers to summarize.

    Returns:
        A JSON string containing normalized Semantic Scholar matches and
        citation metadata, or a graceful fallback payload if the API fails.
    """

    return _search_semantic_scholar(query=query, limit=limit)


@mcp.tool()
def check_github_repo(repo_url: str) -> str:
    """Check the authenticity and health of a GitHub repository.

    Args:
        repo_url: Public GitHub repository URL cited by the paper authors.

    Returns:
        A JSON string containing normalized repository availability and health
        signals, or a graceful fallback payload if the external check fails.
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
