"""Semantic Scholar search tool for literature and citation checks."""

from __future__ import annotations

import json
from urllib import parse, request
from urllib.error import URLError

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper/search"


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def search_semantic_scholar(query: str, limit: int = 3) -> str:
    """Search Semantic Scholar and return a machine-readable JSON payload."""

    normalized_query = _clean_text(query)
    if not normalized_query:
        return json.dumps(
            {
                "tool": "search_semantic_scholar",
                "status": "error",
                "query": normalized_query,
                "summary": "Semantic Scholar search skipped because no query was provided.",
                "results": [],
            },
            ensure_ascii=False,
        )

    safe_limit = max(1, min(limit, 5))
    encoded_query = parse.quote(normalized_query)
    api_url = (
        f"{SEMANTIC_SCHOLAR_API}?query={encoded_query}&limit={safe_limit}"
        "&fields=title,authors,year,citationCount,influentialCitationCount,url,venue,paperId"
    )
    api_request = request.Request(
        api_url,
        headers={"User-Agent": "Academic-Paper-Analyzer-Agent/1.0"},
    )

    try:
        with request.urlopen(api_request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        return json.dumps(
            {
                "tool": "search_semantic_scholar",
                "status": "error",
                "query": normalized_query,
                "summary": f"Semantic Scholar search failed due to network error ({exc}).",
                "results": [],
            },
            ensure_ascii=False,
        )
    except json.JSONDecodeError as exc:
        return json.dumps(
            {
                "tool": "search_semantic_scholar",
                "status": "error",
                "query": normalized_query,
                "summary": f"Semantic Scholar search failed due to invalid JSON response ({exc}).",
                "results": [],
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {
                "tool": "search_semantic_scholar",
                "status": "error",
                "query": normalized_query,
                "summary": f"Semantic Scholar search failed due to unexpected API error ({exc}).",
                "results": [],
            },
            ensure_ascii=False,
        )

    papers = payload.get("data") or []
    if not papers:
        return json.dumps(
            {
                "tool": "search_semantic_scholar",
                "status": "no_results",
                "query": normalized_query,
                "summary": f"No Semantic Scholar results found for query '{normalized_query}'.",
                "results": [],
            },
            ensure_ascii=False,
        )

    results: list[dict[str, object]] = []
    for index, paper in enumerate(papers, start=1):
        authors = paper.get("authors") or []
        author_names = [
            _clean_text(str(author.get("name") or ""))
            for author in authors
            if _clean_text(str(author.get("name") or ""))
        ]
        results.append(
            {
                "result_rank": index,
                "title": _clean_text(str(paper.get("title") or "Untitled")),
                "authors": author_names,
                "year": paper.get("year"),
                "citation_count": int(paper.get("citationCount") or 0),
                "influential_citation_count": int(paper.get("influentialCitationCount") or 0),
                "venue": _clean_text(str(paper.get("venue") or "")) or None,
                "source_url": _clean_text(str(paper.get("url") or "")) or None,
                "paper_id": _clean_text(str(paper.get("paperId") or "")) or None,
            }
        )

    top_result = results[0]
    top_title = str(top_result.get("title") or "Untitled")
    top_year = str(top_result.get("year") or "Unknown year")
    summary = (
        f"Top Semantic Scholar result for '{normalized_query}' is '{top_title}' ({top_year}) "
        f"with {int(top_result.get('citation_count') or 0)} citations."
    )

    return json.dumps(
        {
            "tool": "search_semantic_scholar",
            "status": "ok",
            "query": normalized_query,
            "summary": summary,
            "results": results,
        },
        ensure_ascii=False,
    )
